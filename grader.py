"""
grader.py
AI 評分模組 — 使用 Gemini API 進行四維度加權評分
校正版本：2026-04，基於 7 份真實樣本校正

評分面向：
  A. AI Use Strategy / Prompt Quality     (25%)
  B. Knowledge Restructuring Quality      (30%)
  C. Learning Material Value              (25%)
  D. Personal Learning Trace              (20%)

等級對應：
  4.5–5.0 → Excellent
  3.5–4.4 → Very Good
  2.5–3.4 → Good
  1.0–2.4 → Fair
"""

import os
import re
import time
import json
import random
import logging
from datetime import datetime
from typing import Tuple

import google.generativeai as genai

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 模型設定
# ─────────────────────────────────────────────
DEFAULT_MODEL  = "gemini-2.5-flash-lite"
FALLBACK_MODEL = "gemini-2.5-flash"

# Settings 允許的模型白名單
_ALLOWED_MODELS = {
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite-preview-06-17",  # 向下相容舊設定值
}


def get_active_model() -> str:
    """
    從 storage.get_settings() 讀取 ai_model。
    每次呼叫都重新讀取（storage 有 session_state 快取，
    老師在 Settings 儲存後快取已同步更新，所以這裡讀到的是最新值）。
    若設定值不在白名單則退回 DEFAULT_MODEL。
    """
    try:
        import storage as _storage
        model = _storage.get_settings().get("ai_model", DEFAULT_MODEL)
        if model in _ALLOWED_MODELS:
            return model
        # 相容舊 preview 名稱：含 flash-lite 就用 lite，含 flash 就用 flash
        if "flash-lite" in model:
            return "gemini-2.5-flash-lite"
        if "flash" in model:
            return "gemini-2.5-flash"
    except Exception:
        pass
    return DEFAULT_MODEL

# ─────────────────────────────────────────────
# 系統 Prompt（校正版）
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are an academic grading assistant evaluating English study notes submitted by graduate students in an AI Classification course. The professor allows and encourages AI tool use. Your task is to assess how well the student used AI to create high-quality learning materials.

Evaluate the notes across FOUR dimensions. For each dimension, assign a score from 1 to 5. Then compute a weighted final score.

---

## DIMENSION A — AI Use Strategy / Prompt Quality (Weight: 25%)

Look for: Is the prompt included in the notes? If yes, assess its quality.

5 — Highly strategic: clear learner background, specific source materials listed, detailed output requirements, demonstrates intentional AI collaboration
4 — Partially strategic: specifies a learning focus, language requirements, or personal context, but not all elements present
3 — Functional but generic: gives clear task instructions but lacks learning background or strategic framing
2 — Vague: generic instructions with no learning strategy (e.g., "summarize the lecture")
1 — No prompt shown, or a single very short instruction with no context

If no prompt is visible, score this dimension 2 unless there is strong indirect evidence of AI strategy in the notes themselves.

---

## DIMENSION B — Knowledge Restructuring Quality (Weight: 30%)

Look for: Has the student transformed, not just summarized, the source material?

Evidence of restructuring includes:
- Question-driven chapter/section design (e.g., "Why does CNN need deep stacking?")
- Comparison tables between concepts
- Thematic regrouping of ideas from multiple sources
- Meaningful renaming or reframing of concepts
- Scaffolded learning structures (prerequisites, workflows, decision frameworks)
- Integrating multiple source materials into a unified structure

5 — Comprehensive restructuring: multiple techniques used coherently throughout
4 — Clear restructuring: at least one strong restructuring technique applied meaningfully
3 — Partial restructuring: some structure beyond summarization, but sections still feel like compressed originals
2 — Mostly summary: minor reorganization, but primarily reproduces source structure
1 — No restructuring: pure transcript or bullet-point transcription

---

## DIMENSION C — Learning Material Value (Weight: 25%)

Ask: Could a student use this as a standalone study tool to understand and review the topic?

5 — Excellent learning material: comprehensive coverage, appropriate density, glossary or quick-reference features, immediately usable for revision
4 — Strong learning material: covers key concepts well, clear structure, good for review
3 — Adequate: useful but incomplete; some sections are thin or hard to follow
2 — Limited value: too short, too surface-level, or missing important concepts
1 — Very low value: would not help a student understand or review the topic

---

## DIMENSION D — Personal Learning Trace (Weight: 20%)

Personal learning trace is NOT limited to first-person reflection paragraphs. Accept ANY of:
- First-person observations, doubts, or connections in the text
- Personal naming conventions (e.g., student-invented mnemonics or labels like "Triple BAM Rule")
- Connection to the student's own field, profession, or prior knowledge
- Prompt design that reveals personal learning needs or background
- Section design choices that reflect the student's own learning priorities

5 — Pervasive personal trace: multiple forms present throughout, clearly the student's own learning journey
4 — Meaningful personal trace: at least one form clearly present and genuine
3 — Superficial trace: reflection section exists but is mostly generic, or only minimal personal framing
2 — Minimal trace: very little evidence the student personalized this material
1 — No trace: entirely generic, could have been written by anyone

---

## SCORING LOGIC

Compute the weighted score:
  weighted_score = (A × 0.25) + (B × 0.30) + (C × 0.25) + (D × 0.20)

Map to grade:
  4.5–5.0 → Excellent
  3.5–4.4 → Very Good
  2.5–3.4 → Good
  1.0–2.4 → Fair

SOFT CEILING RULE (apply only when BOTH conditions are true):
  - D = 1 (no personal trace whatsoever)
  - B ≤ 2 (no meaningful restructuring)
  In this case only, cap the grade at "Good" regardless of weighted score.
  DO NOT apply ceiling based solely on low D score.

---

## LANGUAGE COMPLIANCE

After grading, assess the language of the notes:
- chinese_dominant: >70% Chinese text
- mixed: roughly even mix of Chinese and English
- english_compliant: >70% English text

Exception: Chinese annotations or bilingual labels within English text are acceptable and should NOT reduce scores.

---

## OUTPUT FORMAT

Return ONLY a valid JSON object. No preamble, no markdown, no explanation outside the JSON.

{
  "dimension_scores": {
    "A_ai_strategy": <1-5>,
    "B_knowledge_restructuring": <1-5>,
    "C_learning_material_value": <1-5>,
    "D_personal_trace": <1-5>
  },
  "weighted_score": <float, 1 decimal place>,
  "grade": "<Excellent | Very Good | Good | Fair>",
  "soft_ceiling_applied": <true | false>,
  "language_compliance": "<chinese_dominant | mixed | english_compliant>",
  "key_evidence": {
    "A_evidence": "<1-2 sentences citing specific prompt features or their absence>",
    "B_evidence": "<1-2 sentences citing specific restructuring techniques observed>",
    "C_evidence": "<1-2 sentences on usability and coverage>",
    "D_evidence": "<1-2 sentences citing specific personal trace evidence or its absence>"
  },
  "needs_review": <true | false>,
  "needs_review_reason": "<brief reason if needs_review is true, else null>"
}

Set needs_review = true when:
- weighted_score falls on a grade boundary (3.3–3.7 or 4.3–4.7)
- dimension scores have high variance (max - min >= 3)
- language_compliance is chinese_dominant or mixed
- confidence in assessment is low
"""

# ─────────────────────────────────────────────
# 等級對應（顯示用）
# ─────────────────────────────────────────────
GRADE_TO_DISPLAY = {
    "Excellent":  {"label": "Excellent",  "emoji": "🌟", "color": "gold"},
    "Very Good":  {"label": "Very Good",  "emoji": "✅", "color": "green"},
    "Good":       {"label": "Good",       "emoji": "👍", "color": "blue"},
    "Fair":       {"label": "Fair",       "emoji": "⚠️", "color": "orange"},
}

# weighted_score → 舊版 final_score 對應（與 Google Sheets 相容）
GRADE_TO_SCORE = {
    "Excellent":  5,
    "Very Good":  4,
    "Good":       3,
    "Fair":       2,
}


# ─────────────────────────────────────────────
# 主要評分函式
# ─────────────────────────────────────────────
def grade(
    text: str,
    key_concepts: str = "",
    model: str = DEFAULT_MODEL,
    max_retries: int = 3,
) -> Tuple[int, str, bool, dict]:
    """
    對筆記文字進行 AI 評分。

    Args:
        text         : 筆記文字
        key_concepts : 週次關鍵概念（可為空）
        model        : 實際使用的模型名稱，由呼叫端傳入 get_active_model() 的結果
        max_retries  : 最大重試次數（遇到 429 不重試，立即中止）

    Returns:
        (final_score, justification, needs_review, log)

        final_score : int，0 = 失敗未完成評分，2–5 = 正常結果
        log dict 固定包含：
          model_name, graded_at, retry_count,
          request_status, input_tokens_est, language_compliance
        request_status 值：success / rate_limit / parse_error / failed / skipped
    """
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _base_log(model_name, graded_at, retry_count, status, tokens, lang):
        return {
            "model_name":          model_name,
            "graded_at":           graded_at,
            "retry_count":         retry_count,
            "request_status":      status,
            "input_tokens_est":    tokens,
            "language_compliance": lang,
        }

    def _fail(score, justification, needs_review, status,
              model_name=model, retry_count=0, tokens=0, lang=""):
        return score, justification, needs_review, _base_log(
            model_name, "", retry_count, status, tokens, lang)

    # ── 空內容 ──────────────────────────────────
    if not text or len(text.strip()) < 10:
        return _fail(0, "Submission is empty or unreadable.", False, "skipped")

    # ── 語言預檢 ────────────────────────────────
    chinese_ratio       = _chinese_ratio(text)
    language_compliance = _detect_language(chinese_ratio)

    # 純中文直接給 Fair，不呼叫 API
    if chinese_ratio > 0.70:
        log = _base_log(model, _now(), 0, "success", len(text[:8000]), "chinese_dominant")
        detail = _build_detail("Fair", 2.0, {
            "A_ai_strategy": 1, "B_knowledge_restructuring": 1,
            "C_learning_material_value": 1, "D_personal_trace": 1,
        }, "chinese_dominant", False, {
            "A_evidence": "Notes are primarily in Chinese; no English prompt detected.",
            "B_evidence": "Cannot assess English restructuring quality.",
            "C_evidence": "Notes do not meet the English language requirement.",
            "D_evidence": "Cannot assess personal trace in Chinese notes.",
        })
        log.update(detail)
        return 2, "The notes are primarily written in Chinese. English notes are required.", True, log

    # ── 截斷 ────────────────────────────────────
    sample_text      = text[:8000]
    input_tokens_est = len(sample_text) // 2

    # ── Gemini API 呼叫 ──────────────────────────
    retry_count = 0
    for attempt in range(max_retries):
        retry_count = attempt
        try:
            genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
            used_model = model if attempt == 0 else FALLBACK_MODEL

            gemini_model = genai.GenerativeModel(
                model_name=used_model,
                system_instruction=SYSTEM_PROMPT,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=1024,
                    temperature=0.1,
                ),
            )

            prompt = f"Please grade the following student English notes:\n\n---\n{sample_text}\n---"
            if key_concepts:
                prompt += f"\n\nKey concepts for this week: {key_concepts}"

            response  = gemini_model.generate_content(prompt)
            raw       = response.text.strip()
            score, justification, needs_review, detail = _parse_response(raw, language_compliance)
            log = _base_log(used_model, _now(), retry_count, "success", input_tokens_est, language_compliance)
            log.update(detail)
            return score, justification, needs_review, log

        except Exception as e:
            err_str = str(e)
            logger.warning(f"Gemini API attempt {attempt + 1} failed: {err_str[:120]}")

            # 429：立即中止，不再 retry
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                return _fail(
                    0,
                    "Rate limit reached (429). Please wait 1 minute and try again. / "
                    "已達API速率上限，請等待1分鐘後再試。",
                    True, "rate_limit",
                    model_name=used_model,
                    retry_count=retry_count,
                    tokens=input_tokens_est,
                    lang=language_compliance,
                )

            if attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)

    # ── 所有 retry 耗盡 ─────────────────────────
    return _fail(
        0,
        "AI grading failed after multiple attempts. Manual review required.",
        True, "failed",
        retry_count=retry_count,
        tokens=input_tokens_est,
        lang=language_compliance,
    )


# ─────────────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────────────
def _parse_response(raw: str, language_compliance: str) -> Tuple[int, str, bool, dict]:
    """解析 Gemini 回傳的 JSON"""
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(cleaned)

        dim = data.get("dimension_scores", {})
        a = max(1, min(5, int(dim.get("A_ai_strategy", 2))))
        b = max(1, min(5, int(dim.get("B_knowledge_restructuring", 2))))
        c = max(1, min(5, int(dim.get("C_learning_material_value", 2))))
        d = max(1, min(5, int(dim.get("D_personal_trace", 2))))

        weighted = round(a * 0.25 + b * 0.30 + c * 0.25 + d * 0.20, 1)

        # 等級判斷
        grade_str = _score_to_grade(weighted)

        # Soft ceiling 規則
        soft_ceiling = False
        if d == 1 and b <= 2:
            soft_ceiling = True
            if grade_str in ("Very Good", "Excellent"):
                grade_str = "Good"

        # 覆蓋 Gemini 自己判斷的 grade（以我們計算為準）
        lang = data.get("language_compliance", language_compliance)
        evidence = data.get("key_evidence", {})
        needs_review = bool(data.get("needs_review", False))

        # 額外的 needs_review 觸發條件
        if weighted >= 3.3 and weighted <= 3.7:
            needs_review = True
        if weighted >= 4.3 and weighted <= 4.7:
            needs_review = True
        if max(a, b, c, d) - min(a, b, c, d) >= 3:
            needs_review = True
        if lang in ("chinese_dominant", "mixed"):
            needs_review = True

        # 組合評語
        justification = _build_justification(grade_str, weighted, a, b, c, d, evidence)

        final_score = GRADE_TO_SCORE.get(grade_str, 2)
        detail = _build_detail(grade_str, weighted, {
            "A_ai_strategy": a,
            "B_knowledge_restructuring": b,
            "C_learning_material_value": c,
            "D_personal_trace": d,
        }, lang, soft_ceiling, evidence)

        return final_score, justification, needs_review, detail

    except Exception as ex:
        logger.error(f"Parse error: {ex} | raw: {raw[:300]}")
        return (
            0,
            "Could not parse AI response. Manual review required.",
            True,
            {
                "model_name":          "",
                "graded_at":           "",
                "retry_count":         0,
                "request_status":      "parse_error",
                "input_tokens_est":    0,
                "language_compliance": language_compliance,
            },
        )


def _score_to_grade(weighted: float) -> str:
    if weighted >= 4.5:
        return "Excellent"
    elif weighted >= 3.5:
        return "Very Good"
    elif weighted >= 2.5:
        return "Good"
    else:
        return "Fair"


def _build_justification(grade_str, weighted, a, b, c, d, evidence) -> str:
    lines = [
        f"Grade: {grade_str} (Weighted Score: {weighted}/5.0)",
        f"A-Prompt Strategy: {a}/5 | B-Knowledge Restructuring: {b}/5 | "
        f"C-Learning Value: {c}/5 | D-Personal Trace: {d}/5",
    ]
    if evidence.get("B_evidence"):
        lines.append(f"Restructuring: {evidence['B_evidence']}")
    if evidence.get("A_evidence"):
        lines.append(f"Prompt: {evidence['A_evidence']}")
    return " | ".join(lines)[:600]


def _build_detail(grade_str, weighted, dim_scores, lang, soft_ceiling, evidence) -> dict:
    return {
        "grade": grade_str,
        "weighted_score": weighted,
        "dimension_scores": dim_scores,
        "language_compliance": lang,
        "soft_ceiling_applied": soft_ceiling,
        "key_evidence": evidence,
    }


def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars = len([c for c in text if c.strip()])
    return chinese_chars / total_chars if total_chars > 0 else 0.0


def _detect_language(ratio: float) -> str:
    if ratio > 0.70:
        return "chinese_dominant"
    elif ratio > 0.30:
        return "mixed"
    else:
        return "english_compliant"


# ─────────────────────────────────────────────
# 向下相容包裝（舊版 admin_grading.py 呼叫用）
# ─────────────────────────────────────────────
def grade_compat(text: str, model: str = DEFAULT_MODEL) -> Tuple[int, str, bool]:
    """
    舊版相容介面：只回傳 (score, justification, needs_review)
    給尚未更新的 admin_grading.py 使用。
    """
    score, justification, needs_review, _ = grade(text, model)
    return score, justification, needs_review
