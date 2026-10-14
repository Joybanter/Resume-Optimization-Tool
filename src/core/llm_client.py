"""DeepSeek LLM 客户端（PRD 3.2.4 / 4.3 / 8）。

DeepSeek API 兼容 OpenAI 格式，直接复用 openai SDK。
本模块封装优化流程的两次调用：
- analyze：简历理解 + JD 分析 + 改写策略（JSON）
- rewrite：基于策略的段落级改写（JSON）

错误处理（PRD 8）：
- API Key 无效 → LLMAuthError
- 额度不足 → LLMQuotaError
- 超时/网络 → 自动重试 1 次，仍失败抛 LLMNetworkError
- 返回非 JSON → 从文本中提取 JSON（剥掉 markdown 围栏），
  仍失败抛 LLMResponseError
"""

from __future__ import annotations

import json
import logging
import re
import time

logger = logging.getLogger(__name__)

# 调用参数
ANALYZE_TEMPERATURE = 1.0
REWRITE_TEMPERATURE = 1.0
# 输出上限：会按 config.MODEL_MAX_OUTPUT_TOKENS 对当前模型封顶。
# analyze 需要输出逐段策略，长简历下策略较长，给 32K；
# rewrite 已按批次切分（见 resume_optimizer._split_batches），单批输出小，16K 富余。
ANALYZE_MAX_TOKENS = 32768
REWRITE_MAX_TOKENS = 16384
REQUEST_TIMEOUT_SECONDS = 180
MAX_RETRIES = 1  # PRD 8：超时自动重试 1 次


class LLMError(Exception):
    """LLM 调用相关错误基类。"""


class LLMAuthError(LLMError):
    """API Key 无效或未授权。"""


class LLMQuotaError(LLMError):
    """API 额度不足。"""


class LLMNetworkError(LLMError):
    """网络连接失败或超时。"""


class LLMResponseError(LLMError):
    """AI 返回内容异常（无法解析出 JSON）。"""


class LLMCanceledError(LLMError):
    """调用被用户取消。"""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json_object(text: str) -> dict:
    """从模型输出中提取 JSON 对象。

    依次尝试：直接解析 → 剥掉 markdown 围栏 → 定位首尾大括号截取。
    全部失败时抛 LLMResponseError（PRD 8）。
    """
    if not text or not text.strip():
        raise LLMResponseError("AI 返回内容为空")

    candidates = [text.strip()]
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    # 定位最外层大括号
    first = text.find("{")
    last = text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise LLMResponseError("AI 返回格式异常，无法解析出 JSON，请重试")


class LLMClient:
    """DeepSeek API 客户端（OpenAI 兼容格式）。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        if not api_key:
            raise LLMAuthError("尚未配置 API Key，请先在设置中填写 DeepSeek API Key。")
        if not base_url:
            raise LLMError("API Base URL 不能为空")
        if not model:
            raise LLMError("未选择模型")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = None  # 延迟创建，便于测试注入

    # ------------------------------------------------------------------
    # 底层调用
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        return self._client

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        cancel_check=None,
    ) -> dict:
        """发起一次要求 JSON 输出的对话，解析并返回 dict。

        cancel_check: 可取消回调（返回 True 表示用户请求取消），
        在重试间隔与调用前检查。
        """
        last_exc: Exception | None = None
        for attempt in range(1 + MAX_RETRIES):
            if cancel_check and cancel_check():
                raise LLMCanceledError("已取消")
            try:
                response = self._get_client().chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=self._cap_max_tokens(max_tokens),
                    response_format={"type": "json_object"},
                )
                choice = response.choices[0]
                content = choice.message.content or ""
                if getattr(choice, "finish_reason", None) == "length":
                    # 输出触及 max_tokens 上限被截断 → JSON 必然损坏，
                    # 与普通解析失败区分开，给出针对性提示
                    raise LLMResponseError(
                        "AI 输出超过长度限制被截断。请重试；若反复出现，"
                        "建议精简简历内容（如删除空白段落）或缩短 JD 后重试。"
                    )
                return extract_json_object(content)
            except LLMError:
                # JSON 解析等业务错误不重试
                raise
            except Exception as exc:
                if not self._is_retryable(exc):
                    raise self._wrap_error(exc) from exc
                last_exc = exc
                if attempt < MAX_RETRIES:
                    wait = 2
                    logger.warning(
                        "LLM 调用失败（%s），%.0f 秒后重试", exc, wait
                    )
                    time.sleep(wait)
        raise self._wrap_error(last_exc)

    def _cap_max_tokens(self, max_tokens: int) -> int:
        """按模型输出上限封顶 max_tokens（PRD 4.3 模型映射表）。

        防止请求超过模型实际输出能力被 API 拒绝。
        """
        from .. import config

        model_max = config.MODEL_MAX_OUTPUT_TOKENS.get(
            self._model, config.DEFAULT_MAX_OUTPUT_TOKENS
        )
        return min(max_tokens, model_max)

    # ------------------------------------------------------------------
    # 业务接口
    # ------------------------------------------------------------------

    def test_connection(self) -> tuple[bool, str]:
        """发送轻量测试请求验证 Key 有效性（PRD 3.2.7）。

        Returns:
            (是否成功, 面向用户的消息)
        """
        try:
            response = self._get_client().chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
            )
            # 能正常返回即视为连接正常
            _ = response.choices[0].message.content
            return True, "连接正常"
        except Exception as exc:
            return False, str(self._wrap_error(exc))

    def analyze_resume(
        self, resume_text: str, jd_text: str, rewrite_level: str, cancel_check=None
    ) -> dict:
        """第 1 次调用：简历理解 + JD 分析 + 改写策略（PRD 3.2.4）。"""
        from ..prompts.analyze_prompt import (
            ANALYZE_SYSTEM_PROMPT,
            build_analyze_user_prompt,
        )

        user_prompt = build_analyze_user_prompt(resume_text, jd_text, rewrite_level)
        return self.chat_json(
            ANALYZE_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=ANALYZE_MAX_TOKENS,
            temperature=ANALYZE_TEMPERATURE,
            cancel_check=cancel_check,
        )

    def rewrite_resume(
        self,
        resume_text: str,
        rewrite_strategy: dict,
        rewrite_level: str,
        paragraph_ids: list[str],
        target_ids: list[str] | None = None,
        new_entries_hint=None,
        cancel_check=None,
    ) -> dict:
        """第 2 次调用：段落级改写（PRD 3.2.4）。

        长简历由调用方按批次切分（resume_optimizer._split_batches），
        每批只要求改写 target_ids 中的段落，避免单次输出触及模型上限
        被截断（PRD 8）。
        Args:
            target_ids: 本批次需要改写的段落 ID 清单
            new_entries_hint: 新增段落要求（策略 new_entries），仅最后一批传入
        """
        from ..prompts.rewrite_prompt import (
            REWRITE_SYSTEM_PROMPT,
            build_rewrite_user_prompt,
        )

        user_prompt = build_rewrite_user_prompt(
            resume_text,
            rewrite_strategy,
            rewrite_level,
            paragraph_ids,
            target_ids=target_ids,
            new_entries_hint=new_entries_hint,
        )
        return self.chat_json(
            REWRITE_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=REWRITE_MAX_TOKENS,
            temperature=REWRITE_TEMPERATURE,
            cancel_check=cancel_check,
        )

    def clean_jd(self, jd_text: str, cancel_check=None) -> str:
        """清理 JD 文本：去除公司介绍等无关内容，只保留岗位要求（PRD 3.2.2）。

        Returns:
            清理后的 JD 文本；无清理价值时返回原文。
        """
        system_prompt = (
            "你是一个岗位 JD 文本清理助手。用户粘贴的 JD 中可能混有公司介绍、"
            "福利待遇、企业宣传等与岗位要求无关的内容。"
            "请只保留岗位职责、任职要求、技能要求等与应聘者直接相关的部分，"
            "保持原有表述，不要改写。以 JSON 格式输出。"
        )
        user_prompt = (
            "请清理以下 JD 文本，去除公司介绍等无关内容，只保留岗位要求部分。\n"
            "若文本已经很干净（全是岗位要求），返回原文即可。\n\n"
            f"{jd_text}\n\n"
            '请以 JSON 格式返回：{"jd": "清理后的岗位要求文本"}'
        )
        result = self.chat_json(
            system_prompt,
            user_prompt,
            max_tokens=2048,
            temperature=0.1,
            cancel_check=cancel_check,
        )
        cleaned = str(result.get("jd", "") or "").strip()
        # 无效清理（返回为空或过短）时回退原文
        if len(cleaned) < max(20, len(jd_text.strip()) // 4):
            return jd_text.strip()
        return cleaned

    # ------------------------------------------------------------------
    # 错误分类
    # ------------------------------------------------------------------

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """超时与连接类错误才重试；鉴权/额度类不重试。"""
        from openai import APIConnectionError, APITimeoutError

        return isinstance(exc, (APIConnectionError, APITimeoutError))

    def _wrap_error(self, exc: Exception) -> LLMError:
        """把底层异常映射为用户可读的业务错误（PRD 8）。"""
        text = f"{type(exc).__name__}: {exc}".lower()
        if isinstance(exc, self._forbidden_or_unauthorized()) or (
            "401" in text or "authentication" in text or "invalid api key" in text
        ):
            return LLMAuthError("API Key 验证失败，请检查 Key 是否正确。")
        if "402" in text or "insufficient" in text or "balance" in text or "quota" in text:
            return LLMQuotaError("API 额度不足，请登录 DeepSeek 平台充值后重试。")
        if "timed out" in text or "timeout" in text:
            return LLMNetworkError("网络超时，请检查网络后重试。")
        if "connection" in text or "network" in text:
            return LLMNetworkError("网络连接失败，请检查网络设置。")
        return LLMError(f"调用失败：{exc}")

    @staticmethod
    def _forbidden_or_unauthorized():
        from openai import AuthenticationError

        return AuthenticationError
