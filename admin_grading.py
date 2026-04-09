"""
admin_grading.py — 後台批改分頁
查看 AI 評分、覆蓋分數、公開成績、PDF 預覽
"""

import streamlit as st
import pandas as pd
import storage


def render(semester: str):
    st.subheader("Grading / 批改管理")

    if not semester:
        st.info("Please set the current semester in Settings.")
        return

    records = storage.load_all_records(semester)
    if not records:
        st.info("No submissions yet.")
        return

    # ── 篩選列 ────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        all_weeks = sorted({str(r.get("week", "")) for r in records})
        week_filter = st.selectbox("Filter by Week / 篩選週次", ["All"] + all_weeks)
    with col2:
        status_filter = st.selectbox(
            "Filter by Status / 篩選狀態",
            ["All", "⚠️ Needs Review", "📄 Scan Only", "📨 Late", "🔒 Unreleased", "✅ Released"]
        )
    with col3:
        search_id = st.text_input("Search Student ID / 搜尋學號", "").strip().upper()

    # 套用篩選
    filtered = records
    if week_filter != "All":
        filtered = [r for r in filtered if str(r.get("week")) == week_filter]
    if status_filter == "⚠️ Needs Review":
        filtered = [r for r in filtered if str(r.get("needs_review", "")).lower() in ("true","1")]
    elif status_filter == "📄 Scan Only":
        filtered = [r for r in filtered if str(r.get("scan_only", "")).lower() in ("true","1")]
    elif status_filter == "📨 Late":
        filtered = [r for r in filtered if str(r.get("is_late", "")).lower() in ("true","1")]
    elif status_filter == "🔒 Unreleased":
        filtered = [r for r in filtered if str(r.get("released", "")).lower() not in ("true","1","yes")]
    elif status_filter == "✅ Released":
        filtered = [r for r in filtered if str(r.get("released", "")).lower() in ("true","1","yes")]
    if search_id:
        filtered = [r for r in filtered if search_id in r.get("student_id", "").upper()]

    st.markdown(f"**Showing {len(filtered)} record(s) / 顯示 {len(filtered)} 筆**")

    # ── 批量公開按鈕 ──────────────────────────────────────────
    if st.button("✅ Release all filtered grades / 批量公開篩選結果的成績"):
        for r in filtered:
            if str(r.get("released", "")).lower() not in ("true","1"):
                storage.update_record(
                    r["student_id"], r["week"], semester, {"released": "True"}
                )
        st.success(f"Released {len(filtered)} grades.")
        st.rerun()

    st.divider()

    # ── 逐筆批改 ──────────────────────────────────────────────
    for idx, rec in enumerate(filtered):
        sid = rec.get("student_id", "")
        name = rec.get("name", "")
        week = rec.get("week", "")
        ai_score = rec.get("ai_score", "")
        final_score = rec.get("final_score", "")
        justification = rec.get("ai_justification", "")
        released = str(rec.get("released", "")).lower() in ("true","1","yes")
        needs_review = str(rec.get("needs_review", "")).lower() in ("true","1")
        scan_only = str(rec.get("scan_only", "")).lower() in ("true","1")
        is_late = str(rec.get("is_late", "")).lower() in ("true","1")
        drive_url = rec.get("drive_url", "")

        # 標題列標記
        flags = []
        if needs_review: flags.append("⚠️")
        if scan_only:    flags.append("📄 Scan")
        if is_late:      flags.append("📨 Late")
        if released:     flags.append("✅")
        else:            flags.append("🔒")
        flag_str = "  ".join(flags)

        display_score = final_score if final_score else ai_score
        header = f"{flag_str}  {sid} — {name}  |  Week {week}  |  Score: {display_score}"

        with st.expander(header):
            # PDF 預覽連結
            if drive_url:
                st.markdown(f"[📄 View PDF in Google Drive / 在 Drive 預覽原始 PDF]({drive_url})")
            else:
                st.caption("PDF not available in Drive.")

            st.markdown(f"**AI Score / AI 分數：** {ai_score}")
            st.markdown(f"**AI Feedback / AI 評語：**  \n{justification}")

            if scan_only:
                st.warning("📄 This is a scanned PDF — AI could not read the text. Please grade manually.")
            if needs_review:
                st.warning("⚠️ This submission requires manual review.")

            # 老師覆蓋分數
            score_options = ["(Use AI score / 使用AI分數)", "7", "6", "5", "4", "3", "2", "0"]
            current_idx = 0
            if final_score and str(final_score) in ["7","6","5","4","3","2","0"]:
                current_idx = score_options.index(str(final_score))
            new_score = st.selectbox(
                "Override score / 老師最終分數",
                score_options,
                index=current_idx,
                key=f"score_{idx}"
            )

            # 公開成績切換
            release_toggle = st.checkbox(
                "Release grade to student / 公開成績給學生",
                value=released,
                key=f"release_{idx}"
            )

            if st.button("💾 Save / 儲存", key=f"save_{idx}"):
                with st.spinner("Saving... / 儲存中，請稍候..."):
                    final = "" if new_score.startswith("(") else new_score
                    storage.update_record(sid, week, semester, {
                        "final_score": final,
                        "released": str(release_toggle),
                    })
                st.success("✅ Saved! / 已儲存！")
                st.rerun()
