"""简历优化主流程编排（PRD 3.2.4 / 4.4）。

完整流程：
1. 解析原简历 Word（段落 / 格式 / 表格 / 列表）
2. 第 1 次 API 调用：简历理解 + 改写策略
3. 第 2 次 API 调用：段落级改写
4. 回填到原 Word 文档副本（保留格式）
5. 按需转换 PDF

进度通过 progress_cb(percent, stage, message) 上报，
取消通过 cancel_check() 回调实现（返回 True 表示用户取消）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .docx_filler import FillResult, build_output_filename, fill_resume
from .docx_parser import ResumeParseError, parse_docx
from .llm_client import (
    LLMAuthError,
    LLMClient,
    LLMError,
    LLMNetworkError,
    LLMQuotaError,
    LLMResponseError,
)
from .pdf_converter import PdfConversionError, convert_docx_to_pdf
from .history_db import HistoryDB

logger = logging.getLogger(__name__)


class OptimizationCanceled(Exception):
    """用户在优化过程中取消。"""


#: 分批改写参数（PRD 8 输出截断防护）：单批最大段落数与字符数。
#: 长简历（如 190+ 段）的单次全量改写会触及模型输出上限导致 JSON 截断，
#: 按批改写后单次输出量可控，从根本上避免截断。
REWRITE_BATCH_MAX_PARAGRAPHS = 25
REWRITE_BATCH_MAX_CHARS = 5000


def _split_batches(
    items: list[tuple[str, str]],
    max_items: int | None = None,
    max_chars: int | None = None,
) -> list[list[tuple[str, str]]]:
    """把待改写段落按段落数/字符数切成若干批。

    Args:
        items: [(段落ID, 段落文本), ...]，保持顺序

    Returns:
        批次列表，每批为若干 (段落ID, 段落文本)。
    """
    if max_items is None:
        max_items = REWRITE_BATCH_MAX_PARAGRAPHS
    if max_chars is None:
        max_chars = REWRITE_BATCH_MAX_CHARS

    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    chars = 0
    for pid, text in items:
        length = len(text)
        if current and (chars + length > max_chars or len(current) >= max_items):
            batches.append(current)
            current, chars = [], 0
        current.append((pid, text))
        chars += length
    if current:
        batches.append(current)
    return batches


def _extract_target_ids(strategy: dict, parsed) -> list[str]:
    """从改写策略提取待改写段落 ID 清单。

    优先采用策略 paragraph_plans 中 action != keep 的段落；
    策略缺失/格式异常时回退为"全部非空正文段落"（不含表格，
    表格内容如姓名、电话通常不应改动）。
    """
    plans = strategy.get("paragraph_plans", []) if isinstance(strategy, dict) else []
    target_ids: list[str] = []
    seen: set[str] = set()
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        action = str(plan.get("action", "modify")).strip().lower()
        pid = str(plan.get("paragraph_id", "")).strip()
        if not pid or pid in seen or action == "keep":
            continue
        para = parsed.get(pid)
        if para is not None and not para.is_empty:
            seen.add(pid)
            target_ids.append(pid)

    if not target_ids:
        logger.warning("策略未给出可执行的段落计划，回退为改写全部非空正文段落")
        target_ids = [
            p.para_id for p in parsed.paragraphs if not p.is_empty and not p.in_table
        ]
    return target_ids


@dataclass
class OptimizeRequest:
    """一次优化任务的输入。"""

    resume_path: str
    jd_text: str
    jd_title: str  # 岗位名称（用于输出文件命名与历史记录）
    rewrite_level: str  # conservative / moderate / deep
    output_dir: str  # 导出目录
    export_pdf: bool = True
    export_word: bool = True

    def validate(self) -> None:
        if not Path(self.resume_path).exists():
            raise ResumeParseError(f"简历文件不存在：{self.resume_path}")
        if not self.jd_text or not self.jd_text.strip():
            raise ValueError("请先粘贴目标岗位的 JD 文本。")
        if self.rewrite_level not in ("conservative", "moderate", "deep"):
            raise ValueError("请选择改写尺度（保守 / 中度 / 深度）。")


@dataclass
class OptimizeResult:
    """一次优化任务的输出。"""

    request: OptimizeRequest
    model: str = ""
    original_paragraphs: list[tuple[str, str]] = field(default_factory=list)
    paragraphs_map: dict[str, str] = field(default_factory=dict)
    new_paragraphs: list[dict] = field(default_factory=list)
    summary: str = ""
    docx_path: str = ""
    pdf_path: str = ""
    pdf_error: str = ""  # PDF 转换失败的原因（Word 已生成时不影响整体流程）
    fill_stats: FillResult = field(default_factory=FillResult)
    modified_count: int = 0
    inserted_count: int = 0


class ResumeOptimizer:
    """优化流程编排器：解析 → 分析 → 改写 → 回填 → 导出。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        client_factory=None,
    ) -> None:
        """client_factory 供测试注入假 LLM 客户端，默认为真实 LLMClient。"""
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._client_factory = client_factory or LLMClient

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run(
        self,
        request: OptimizeRequest,
        progress_cb=None,
        cancel_check=None,
    ) -> OptimizeResult:
        """执行完整优化流程。

        Args:
            request: 优化任务输入
            progress_cb: 进度回调 (percent: int, stage: str, message: str)
            cancel_check: 取消检查回调，返回 True 时中止流程

        Raises:
            OptimizationCanceled: 用户取消
            ResumeParseError: 简历解析失败
            LLMError 及子类: API 调用失败
            PdfConversionError: PDF 转换失败（Word 已生成）
        """
        request.validate()

        def report(percent: int, stage: str, message: str) -> None:
            if progress_cb:
                progress_cb(percent, stage, message)

        def check_cancel() -> None:
            if cancel_check and cancel_check():
                raise OptimizationCanceled("已取消优化")

        result = OptimizeResult(request=request, model=self._model)

        # ---- 步骤 1：解析 Word ----
        report(5, "parse", "正在解析简历 Word 文档…")
        check_cancel()
        parsed = parse_docx(request.resume_path)
        result.original_paragraphs = [(p.para_id, p.text) for p in parsed.paragraphs]
        logger.info(
            "简历解析完成：%s 个段落（正文 %s，表格 %s）",
            len(parsed.paragraphs),
            sum(1 for p in parsed.paragraphs if not p.in_table),
            parsed.table_count,
        )

        # ---- 步骤 2：第一次调用，简历理解 + 改写策略 ----
        report(12, "analyze", "AI 正在理解简历并制定改写策略…（第 1/2 步，长简历约需 1-3 分钟）")
        check_cancel()
        client = self._client_factory(self._api_key, self._base_url, self._model)
        jd_text = request.jd_text.strip()
        analysis = client.analyze_resume(
            resume_text=parsed.to_prompt_text(),
            jd_text=jd_text,
            rewrite_level=request.rewrite_level,
            cancel_check=cancel_check,
        )
        strategy = analysis.get("rewrite_strategy", analysis)
        report(45, "analyze", "改写策略已生成，准备逐段改写…")
        check_cancel()

        # ---- 步骤 3：第二次调用，段落级改写（长简历自动分批，PRD 8 截断防护）----
        from ..prompts.rewrite_prompt import parse_rewrite_result

        target_ids = _extract_target_ids(strategy, parsed)
        batches = _split_batches(
            [(pid, parsed.get(pid).text) for pid in target_ids]
        )
        n_batches = max(1, len(batches))
        new_entries_hint = (
            strategy.get("new_entries") if isinstance(strategy, dict) else None
        )
        logger.info(
            "改写计划：%s 个待改写段落，切分为 %s 批", len(target_ids), n_batches
        )

        all_map: dict[str, str] = {}
        all_new: list[dict] = []
        summary_parts: list[str] = []
        for i, batch in enumerate(batches, start=1):
            check_cancel()
            batch_ids = [pid for pid, _ in batch]
            report(
                50 + int(30 * (i - 1) / n_batches),
                "rewrite",
                f"AI 正在改写简历内容…（第 2/2 步，批次 {i}/{n_batches}，"
                f"本批 {len(batch_ids)} 段，长简历请耐心等待）",
            )
            rewrite_output = client.rewrite_resume(
                resume_text=parsed.to_prompt_text(),
                rewrite_strategy=strategy,
                rewrite_level=request.rewrite_level,
                paragraph_ids=[p.para_id for p in parsed.paragraphs],
                target_ids=batch_ids,
                # 新增段落统一在最后一批生成，避免多批重复
                new_entries_hint=(new_entries_hint if i == n_batches else None),
                cancel_check=cancel_check,
            )
            batch_map, batch_new, batch_summary = parse_rewrite_result(rewrite_output)
            all_map.update(batch_map)
            all_new.extend(batch_new)
            if batch_summary:
                summary_parts.append(batch_summary)

        result.paragraphs_map = all_map
        result.new_paragraphs = all_new
        result.summary = "；".join(summary_parts)[:500]
        report(80, "rewrite", "改写完成，正在回填到 Word 文档…")
        check_cancel()

        # 只保留原文档中真实存在的段落 ID（防御 AI 幻觉 ID）
        valid_map = {}
        for para_id, content in all_map.items():
            if parsed.get(para_id) is not None:
                valid_map[para_id] = content
            else:
                logger.warning("忽略 AI 输出的未知段落 ID：%s", para_id)
        result.paragraphs_map = valid_map
        result.modified_count = sum(
            1 for pid, txt in valid_map.items() if txt.strip() != (parsed.get(pid).text if parsed.get(pid) else "")
        )
        result.inserted_count = len(all_new)

        # ---- 步骤 4：回填 Word 副本 ----
        if request.export_word:
            report(85, "fill", "正在保留原排版回填内容…")
            check_cancel()
            output_dir = Path(request.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = build_output_filename(
                request.resume_path,
                request.jd_title,
                datetime.now().strftime("%Y%m%d"),
                avoid_dir=str(output_dir),
            )
            docx_path = str(output_dir / filename)
            result.fill_stats = fill_resume(
                template_path=request.resume_path,
                output_path=docx_path,
                paragraphs_map=result.paragraphs_map,
                new_paragraphs=result.new_paragraphs,
            )
            result.docx_path = docx_path
            logger.info(
                "回填完成：替换 %s 段，新增 %s 段，跳过 %s 段 → %s",
                result.fill_stats.replaced,
                result.fill_stats.inserted,
                result.fill_stats.skipped,
                docx_path,
            )
        report(95, "fill", "Word 导出完成，准备生成 PDF…")
        check_cancel()

        # ---- 步骤 5：PDF 导出 ----
        if request.export_pdf and result.docx_path:
            report(96, "pdf", "正在调用 Word 生成 PDF…")
            check_cancel()
            try:
                result.pdf_path = convert_docx_to_pdf(result.docx_path)
            except PdfConversionError as exc:
                # PRD 8：转换失败不阻断主流程，Word 已生成，给出明确提示
                result.pdf_error = str(exc)
                logger.warning("PDF 转换失败（Word 已生成）：%s", exc)

        report(100, "done", "优化完成")
        return result

    # ------------------------------------------------------------------
    # 历史记录（供 GUI 在确认导出后调用）
    # ------------------------------------------------------------------

    @staticmethod
    def save_history(result: OptimizeResult) -> int:
        """保存一条历史记录（PRD 3.2.9）。"""
        db = HistoryDB()
        try:
            return db.add_record(
                resume_path=result.request.resume_path,
                jd_title=result.request.jd_title,
                jd_text=result.request.jd_text,
                rewrite_level=result.request.rewrite_level,
                model=result.model,
                output_docx=result.docx_path,
                output_pdf=result.pdf_path,
                summary=result.summary,
            )
        finally:
            db.close()


__all__ = [
    "OptimizeRequest",
    "OptimizeResult",
    "OptimizationCanceled",
    "ResumeOptimizer",
    "LLMError",
    "LLMAuthError",
    "LLMNetworkError",
    "LLMQuotaError",
    "LLMResponseError",
    "PdfConversionError",
    "ResumeParseError",
]
