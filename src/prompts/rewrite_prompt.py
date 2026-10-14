"""第二次调用 Prompt：基于策略的段落级改写（PRD 4.5）。

输入：原简历全文（带段落 ID）+ 改写策略 JSON + 改写尺度 + 段落 ID 清单
输出（JSON）：与原段落一一对应的改写结果（paragraphs）+ 改写摘要（summary）
"""

from __future__ import annotations

import json

from .analyze_prompt import REWRITE_LEVELS, summarize_strategy_for_prompt

REWRITE_SYSTEM_PROMPT = """你是一位资深简历优化专家，擅长在不改变事实的前提下，
将简历经历重新表达为目标岗位语境下最有说服力的描述。
你收到带 [pN] 段落ID标记的原简历和一份改写策略，需要逐段落产出改写结果。
请以 JSON 格式输出，不要输出任何 JSON 以外的内容。"""


def build_rewrite_user_prompt(
    resume_text: str,
    rewrite_strategy: dict,
    rewrite_level: str,
    paragraph_ids: list[str] | None = None,
    target_ids: list[str] | None = None,
    new_entries_hint=None,
) -> str:
    """组装第二次调用的用户 Prompt（PRD 4.5 模板）。

    Args:
        target_ids: 本批次需要改写的段落 ID（长简历分批改写时提供）；
                    为空时按策略全量改写（兼容单批模式）
        new_entries_hint: 新增段落要求（策略 new_entries），仅最后一批传入
    """
    level_desc = REWRITE_LEVELS.get(rewrite_level, REWRITE_LEVELS["moderate"])
    strategy_json = summarize_strategy_for_prompt(rewrite_strategy)
    ids_hint = ""
    if paragraph_ids:
        ids_hint = (
            "【原简历全部段落ID清单】\n"
            + ", ".join(paragraph_ids)
            + "\n（改写结果的 id 必须取自该清单；新增段落的 id 使用 new_1、new_2 前缀。）\n"
        )

    target_block = ""
    if target_ids:
        target_block = (
            "【本批次需要改写的段落】\n"
            + "\n".join(f"[{pid}]" for pid in target_ids)
            + "\n只输出以上段落的改写结果（id 必须取自该清单）；"
            "其余段落一律不要输出，包括策略中提及但不在本清单中的段落。\n"
        )

    new_block = ""
    if new_entries_hint:
        new_block = (
            "【新增段落要求】\n"
            + json.dumps(new_entries_hint, ensure_ascii=False)
            + "\n请在本批次输出以上要求的新增段落（id 用 new_ 前缀并标注 insert_after，"
            "插入位置必须是原简历中真实存在的段落 ID）。\n"
        )

    return f"""请基于以下信息改写简历内容。

【原简历全文】
{resume_text}

【改写策略】
{strategy_json}

{ids_hint}{target_block}{new_block}【格式约束】
1. 只输出需要改写的段落：改写策略中要求改写（modify/replace）的段落才输出；
   策略中标记 keep 或未提及的段落、以及个人信息（姓名、电话、邮箱等）不要输出
2. 输出的每个段落用 id 标识，与原段落的 [pN] 标记匹配
3. 新增段落使用 new_ 前缀，并标注 insert_after 指明插入到哪个段落之后
4. 保持与原简历相近的篇幅，不要大幅膨胀
5. 改写尺度为 {rewrite_level}（{level_desc}），请严格遵循策略中的改写力度
6. 所有改写必须基于原简历中真实存在的经历和能力，不得凭空捏造完全无关的经历
7. 专业术语使用目标岗位的行业标准表述
8. 语言风格：简洁有力，数据导向，结果导向
9. 表格内的段落（table_ 开头）保持简短，适合同一单元格展示
10. 输出 JSON 必须完整合法，不得超出篇幅限制；宁可少输出段落，不可截断

请以 JSON 格式返回需要改写的段落：
{{
  "paragraphs": [
    {{"id": "p1", "content": "改写后的段落内容"}},
    {{"id": "p2", "content": "改写后的段落内容"}},
    {{"id": "new_1", "insert_after": "p5", "content": "新增段落内容"}}
  ],
  "summary": "本批次改写摘要（100字内）"
}}"""


def parse_rewrite_result(result: dict) -> tuple[dict[str, str], list[dict], str]:
    """整理 rewrite 的 JSON 输出。

    Returns:
        (paragraphs_map, new_paragraphs, summary)
        paragraphs_map: {段落ID: 改写后文本}（仅含原段落）
        new_paragraphs: [{"insert_after": ID, "content": 文本}, ...]
        summary: 改写摘要
    """
    paragraphs = result.get("paragraphs", [])
    if not isinstance(paragraphs, list):
        paragraphs = []

    paragraphs_map: dict[str, str] = {}
    new_paragraphs: list[dict] = []
    for item in paragraphs:
        if not isinstance(item, dict):
            continue
        para_id = str(item.get("id", "")).strip()
        content = str(item.get("content", "") if item.get("content") is not None else "")
        if not para_id:
            continue
        if para_id.startswith("new"):
            new_paragraphs.append(
                {
                    "insert_after": str(item.get("insert_after", "")).strip(),
                    "content": content,
                }
            )
        else:
            paragraphs_map[para_id] = content

    summary = str(result.get("summary", "") or "")
    return paragraphs_map, new_paragraphs, summary