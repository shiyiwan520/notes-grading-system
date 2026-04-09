"""
admin_weeks.py — 週次開放設定分頁
"""
import streamlit as st
import storage


def render(semester: str):
    st.subheader("Week Settings / 週次開放設定")
    if not semester:
        st.info("Please set the current semester in Settings first.")
        return

    st.caption(
        "Toggle each week open/closed. Leave deadline blank for no deadline. "
        "Add key concepts to guide AI grading.  \n"
        "開關週次，截止日留空=無期限，可填入本週重點概念讓 AI 評分更準確。"
    )

    all_weeks = {str(w["week"]): w for w in storage.get_all_weeks(semester)}

    changes = {}
    for i in range(1, 17):
        week_str = str(i).zfill(2)
        existing = all_weeks.get(week_str, {})
        is_open = str(existing.get("open", "False")).lower() in ("true","1","yes")
        deadline = existing.get("deadline", "")
        key_concepts = existing.get("key_concepts", "")

        with st.expander(f"Week {week_str}  {'🟢 Open' if is_open else '⚪ Closed'}"):
            col1, col2 = st.columns([1, 3])
            with col1:
                new_open = st.toggle("Open / 開放", value=is_open, key=f"open_{week_str}")
            with col2:
                new_deadline = st.text_input(
                    "Deadline (YYYY-MM-DD) / 截止日，留空=無期限",
                    value=deadline,
                    disabled=not new_open,
                    key=f"dl_{week_str}"
                )
            new_concepts = st.text_area(
                "Key concepts for AI grading / 本週重點概念（供 AI 評分參考）",
                value=key_concepts,
                placeholder="e.g. present perfect tense, technology vocabulary, note-taking structure",
                height=80,
                disabled=not new_open,
                key=f"kc_{week_str}"
            )
            if st.button(f"Save Week {week_str} / 儲存", key=f"save_week_{week_str}"):
                storage.save_week(semester, week_str, new_open,
                                  new_deadline if new_open else "",
                                  new_concepts if new_open else "")
                st.success(f"Week {week_str} saved! / 已儲存！")
                st.rerun()
