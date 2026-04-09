"""
admin_weeks.py — 週次開放設定分頁（週數由 Settings 控制）
"""
import streamlit as st
import storage


def render(semester: str):
    st.subheader("Week Settings / 週次開放設定")
    if not semester:
        st.info("Please set the current semester in Settings first. / 請先在 Settings 設定目前學期。")
        return

    # 從 settings 讀取總週數
    settings = storage.get_settings()
    try:
        total_weeks = int(settings.get("total_weeks", 16))
    except (ValueError, TypeError):
        total_weeks = 16

    st.caption(
        f"Showing Week 01 – Week {str(total_weeks).zfill(2)}. "
        f"Change total weeks in Settings.  \n"
        f"顯示 Week 01 到 Week {str(total_weeks).zfill(2)}，可在 Settings 修改總週數。"
    )

    all_weeks = {str(w["week"]).zfill(2): w for w in storage.get_all_weeks(semester)}

    for i in range(1, total_weeks + 1):
        week_str = str(i).zfill(2)
        existing = all_weeks.get(week_str, {})
        is_open = str(existing.get("open", "False")).lower() in ("true", "1", "yes")
        deadline = str(existing.get("deadline", "")).strip()
        key_concepts = str(existing.get("key_concepts", "")).strip()

        status = "🟢 Open / 開放" if is_open else "⚪ Closed / 關閉"
        with st.expander(f"Week {week_str}  —  {status}"):
            col1, col2 = st.columns([1, 3])
            with col1:
                new_open = st.toggle(
                    "Open / 開放",
                    value=is_open,
                    key=f"open_{week_str}"
                )
            with col2:
                new_deadline = st.text_input(
                    "Deadline (YYYY-MM-DD) / 截止日，留空=無期限",
                    value=deadline,
                    disabled=not new_open,
                    placeholder="e.g. 2025-10-15",
                    key=f"dl_{week_str}"
                )
            new_concepts = st.text_area(
                "Key concepts for AI grading / 本週重點概念（供 AI 評分參考，留空=使用通用標準）",
                value=key_concepts,
                placeholder="e.g. present perfect tense, technology vocabulary, note-taking structure",
                height=80,
                disabled=not new_open,
                key=f"kc_{week_str}"
            )
            if st.button(f"Save Week {week_str} / 儲存", key=f"save_week_{week_str}"):
                with st.spinner(f"Saving Week {week_str}... / 儲存中，請稍候..."):
                    storage.save_week(
                        semester, week_str, new_open,
                        new_deadline if new_open else "",
                        new_concepts if new_open else ""
                    )
                st.success(f"✅ Week {week_str} saved! / 已儲存！")
                st.rerun()
