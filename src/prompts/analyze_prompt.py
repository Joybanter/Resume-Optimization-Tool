"""第一次调用 Prompt：简历理解 + JD 分析 + 改写策略（PRD 4.5）。

输入：原简历全文（带段落 ID）+ JD 文本 + 改写尺度
输出（JSON）：简历结构化提取 / JD 需求分析 / 匹配度分析 / 改写策略
"""

from __future__ import annotations

import json

ANALYZE_SYSTEM_PROMPT = """你是一位资深猎头和简历优化专家，精通各行各业的岗位要求与人才评估。
你将收到一份求职者的原始简历（每个段落前有 [pN] 或 [table_...] 的段落ID标记）和目标岗位 JD。
你的任务是充分理解原简历与目标岗位，产出一份结构化的改写方案，供下一步精确改写使用。
请以 JSON 格式输出，不要输出任何 JSON 以外的内容。"""


REWRITE_LEVELS = {
    "conservative": (
        "保守模式 — 润色微调：保留原有经历框架，不做跨行业映射；"
        "优化表达方式使语言更贴合目标岗位；替换关键词和术语，增加 JD 中的高频词；"
        "不新增原简历没有的经历条目。适合同行业/相近岗位的简历优化。"
    ),
    "moderate": (
        "中度模式 — 结构重构：基于原有经历，重新组织描述角度和重点；"
        "将原经历中的可迁移能力映射到新岗位语境；替换专业术语，调整描述重点；"
        "适度增补 1-2 条与新岗位高度相关的经历描述（必须基于原有经历延伸）。"
        "适合跨细分方向但同大类岗位。"
    ),
    "deep": (
        "深度模式 — 经历映射：大幅重构经历描述，将原经历场景映射到新岗位场景；"
        "专业术语全面替换；可基于原经历中的可迁移能力，将原有经历重新映射到新场景"
        "（注意：不是无中生有，而是原经历在目标岗位语境下的合理表达）；"
        "调整经历的呈现优先级，突出与新岗位最相关的内容。适合跨行业/跨岗位方向。"
    ),
}


def build_analyze_user_prompt(
    resume_text: str, jd_text: str, rewrite_level: str
) -> str:
    """组装第一次调用的用户 Prompt（PRD 4.5 模板）。"""
    level_desc = REWRITE_LEVELS.get(rewrite_level, REWRITE_LEVELS["moderate"])
    return f"""请完成以下任务：

【输入】
- 原简历全文（每行开头的 [pN] 为段落ID，将在下一步改写时用于逐段对齐）：
{resume_text}

- 目标岗位 JD：
{jd_text}

- 改写尺度：{rewrite_level}
  （{level_desc}）

【任务】
1. 简历结构化提取（输出精简）
   将原简历按模块提取：个人信息、教育背景、工作/实习经历、项目经历、校园经历、技能、自我评价等。
   每个模块用段落范围表示（如 "p1-p5"），一句话概括内容；不要逐个罗列段落ID。

2. JD 需求分析
   - 提取硬性要求（学历、年限、技能等）
   - 提取加分项
   - 提取关键词和高频术语

3. 匹配度分析（各条目一句话，精简输出）
   - 原简历中哪些经历/能力可迁移到目标岗位（最多 8 条）
   - 哪些需求在原简历中没有对应（最多 8 条）
   - 可迁移经历如何映射到新岗位语境（最多 10 条）

4. 改写策略（输出必须精简，不要冗余解释）
   - paragraph_plans 完整列出所有需要改写的段落（action 为 modify/replace），
     保持原样的段落（如个人信息、无需变化的条目）不要列入；
     每条 strategy 用一句话说明改法（替换术语 / 重构描述 / 映射场景）
   - 需要新增哪些经历条目（仅中度和深度模式，且必须基于原有经历的可迁移能力）
   - 术语映射表：原文术语 → 目标岗位术语（最多 15 条）

【重要约束】
所有改写必须基于用户原有经历中的可迁移能力进行映射，不得凭空捏造完全无关的经历。
输出 JSON 必须完整合法，不得超出篇幅限制；宁可精简，不可截断。

请以 JSON 格式返回：
{{
  "resume_structure": {{
    "modules": [
      {{"name": "模块名", "paragraph_range": "p1-p5", "content_summary": "..."}}
    ]
  }},
  "jd_analysis": {{
    "hard_requirements": ["..."],
    "bonus_points": ["..."],
    "keywords": ["..."],
    "industry_terms": ["..."]
  }},
  "match_analysis": {{
    "transferable": ["可迁移的经历/能力"],
    "gaps": ["缺失的需求"],
    "mapping": [{{"original": "原经历", "mapped_to": "新岗位语境下的描述"}}]
  }},
  "rewrite_strategy": {{
    "paragraph_plans": [
      {{"paragraph_id": "p1", "action": "keep|modify|replace", "strategy": "具体改写策略"}}
    ],
    "new_entries": [
      {{"insert_after": "p5", "content_description": "新增经历的描述方向", "basis": "基于哪条原经历的可迁移能力"}}
    ],
    "term_mapping": [
      {{"original": "原术语", "target": "目标术语"}}
    ]
  }}
}}"""


def summarize_strategy_for_prompt(strategy: dict) -> str:
    """将策略 dict 压缩为下一步可读的 JSON 文本（截断保护）。"""
    text = json.dumps(strategy, ensure_ascii=False, indent=2)
    if len(text) > 12000:
        text = text[:12000] + "\n... (策略过长已截断)"
    return text
