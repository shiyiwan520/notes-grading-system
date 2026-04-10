"""
admin_grading_ui_patch.py
在 admin_grading.py 中，找到顯示 ai_justification 的地方，
用以下函式替換，就能呈現四維度分數卡片。

使用方式：
  在 admin_grading.py 頂部 import：
    from admin_grading_ui_patch import show_ai_grade_detail

  在顯示每筆記錄的地方呼叫：
    show_ai_grade_detail(row)
"""

import streamlit as st


GRADE_COLOR = {
    "Excellent": "#FFD700",   # 金色
    "Very Good": "#28a745",   # 綠色
    "Good":      "#007bff",   # 藍色
    "Fair":      "#fd7e14",   # 橙色
}

GRADE_EMOJI = {
    "Excellent": "🌟",
    "Very Good": "✅",
    "Good":      "👍",
    "Fair":      "⚠️",
}

LANG_BADGE = {
    "english_compliant": ("✅ English", "green"),
    "mixed":             ("🟡 Mixed",   "orange"),
    "chinese_dominant":  ("🔴 Chinese", "red"),
}


def show_ai_grade_detail(row: dict):
    """
    row 是 Google Sheets 的一列資料（dict）
    讀取 ai_justification 字串，解析並顯示四維度卡片。

    ai_justification 格式（grader.py 產出）：
    "Grade: Very Good (Weighted Score: 3.8/5.0) | A-Prompt Strategy: 4/5 | ..."
    """
    justification = row.get("ai_justification", "")
    language = row.get("language_compliance", "")

    # ── 嘗試從 justification 解析分數 ──
    grade_str, weighted, a, b, c, d = _parse_justification(justification)

    # ── Grade Badge ──
    color = GRADE_COLOR.get(grade_str, "#aaa")
    emoji = GRADE_EMOJI.get(grade_str, "")
    st.markdown(
        f"<div style='background:{color}22; border-left:4px solid {color}; "
        f"padding:8px 12px; border-radius:6px; margin-bottom:8px;'>"
        f"<b style='font-size:1.1em'>{emoji} {grade_str}</b> &nbsp; "
        f"<span style='color:#555'>Weighted Score: <b>{weighted}</b>/5.0</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── 四維度分數條 ──
    if a > 0:
        cols = st.columns(4)
        dims = [
            ("A Prompt", a, "#6c63ff"),
            ("B Restructuring", b, "#17a2b8"),
            ("C Value", c, "#28a745"),
            ("D Trace", d, "#fd7e14"),
        ]
        for col, (label, score, bar_color) in zip(cols, dims):
            with col:
                pct = int(score / 5 * 100)
                st.markdown(
                    f"<div style='font-size:0.8em; color:#555; margin-bottom:2px'>{label}</div>"
                    f"<div style='background:#eee; border-radius:4px; height:8px; margin-bottom:2px'>"
                    f"<div style='background:{bar_color}; width:{pct}%; height:8px; border-radius:4px'></div></div>"
                    f"<div style='font-size:0.9em; font-weight:bold'>{score}/5</div>",
                    unsafe_allow_html=True,
                )

    # ── 語言標記 ──
    if language:
        badge_text, badge_color = LANG_BADGE.get(language, ("Unknown", "gray"))
        st.markdown(
            f"<span style='background:{badge_color}22; color:{badge_color}; "
            f"border:1px solid {badge_color}; border-radius:4px; "
            f"padding:2px 8px; font-size:0.8em'>{badge_text}</span>",
            unsafe_allow_html=True,
        )

    # ── 原始評語（可折疊） ──
    if justification:
        with st.expander("AI 評語詳細"):
            st.caption(justification)


def _parse_justification(text: str):
    """
    從 justification 字串解析各維度分數。
    格式：
    "Grade: Very Good (Weighted Score: 3.8/5.0) | A-Prompt Strategy: 4/5 | B-...: 3/5 | ..."
    """
    import re

    grade_str = "—"
    weighted = 0.0
    a = b = c = d = 0

    try:
        m = re.search(r"Grade:\s*([\w\s]+?)\s*\(Weighted Score:\s*([\d.]+)", text)
        if m:
            grade_str = m.group(1).strip()
            weighted = float(m.group(2))

        m2 = re.search(
            r"A-Prompt Strategy:\s*(\d)/5.*?B-Knowledge Restructuring:\s*(\d)/5.*?"
            r"C-Learning Value:\s*(\d)/5.*?D-Personal Trace:\s*(\d)/5",
            text,
        )
        if m2:
            a, b, c, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3)), int(m2.group(4))
    except Exception:
        pass

    return grade_str, weighted, a, b, c, d
