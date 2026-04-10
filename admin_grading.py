"""
admin_grading.py — 批改管理分頁
含：評語編輯、PDF 下載、批量下載整週
"""

import streamlit as st
import pandas as pd
import zipfile
import io
import requests
import storage


def render(semester: str):
    st.subheader("Grading / 批改管理")

    if not semester:
        st.info("Please set the current semester in Settings first.")
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

    filtered = records
    if week_filter != "All":
        filtered = [r for r in filtered if str(r.get("week")) == week_filter]
    if status_filter == "⚠️ Needs Review":
        filtered = [r for r in filtered if str(r.get("needs_review","")).lower() in ("true","1")]
    elif status_filter == "📄 Scan Only":
        filtered = [r for r in filtered if str(r.get("scan_only","")).lower() in ("true","1")]
    elif status_filter == "📨 Late":
        filtered = [r for r in filtered if str(r.get("is_late","")).lower() in ("true","1")]
    elif status_filter == "🔒 Unreleased":
        filtered = [r for r in filtered if str(r.get("released","")).lower() not in ("true","1","yes")]
    elif status_filter == "✅ Released":
        filtered = [r for r in filtered if str(r.get("released","")).lower() in ("true","1","yes")]
    if search_id:
        filtered = [r for r in filtered if search_id in r.get("student_id","").upper()]

    st.markdown(f"**Showing {len(filtered)} record(s) / 顯示 {len(filtered)} 筆**")

    # ── 批量操作 ──────────────────────────────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("✅ Release all filtered / 批量公開篩選成績"):
            for r in filtered:
                if str(r.get("released","")).lower() not in ("true","1"):
                    storage.update_record(r["student_id"], r["week"], semester, {"released": "True"})
            st.success(f"Released {len(filtered)} grades.")
            st.rerun()

    with col_b:
        # 批量下載整週 PDF
        if week_filter != "All":
            week_records = [r for r in filtered if r.get("storage_path","")]
            if week_records:
                if st.button(f"📦 Download all PDFs for Week {week_filter} / 批量下載本週PDF"):
                    with st.spinner(f"Preparing ZIP for Week {week_filter}... / 打包中，請稍候..."):
                        zip_buffer = io.BytesIO()
                        success_count = 0
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                            for rec in week_records:
                                path = rec.get("storage_path","")
                                if not path:
                                    continue
                                signed_url = storage.get_pdf_signed_url(path, expires_in=300)
                                if not signed_url:
                                    continue
                                try:
                                    resp = requests.get(signed_url, timeout=30)
                                    if resp.status_code == 200:
                                        fname = rec.get("original_filename") or f"{rec['student_id']}_Week{week_filter}.pdf"
                                        zf.writestr(fname, resp.content)
                                        success_count += 1
                                except Exception:
                                    pass
                        zip_buffer.seek(0)
                    if success_count > 0:
                        st.download_button(
                            f"📥 Download ZIP ({success_count} files) / 下載壓縮檔",
                            data=zip_buffer,
                            file_name=f"{semester}_Week{week_filter}_PDFs.zip",
                            mime="application/zip"
                        )
                    else:
                        st.error("Could not download any PDFs. / 無法下載任何 PDF。")

    st.divider()

    # ── 逐筆批改 ──────────────────────────────────────────────
    SCORE_OPTIONS = [
        "(Use AI score / 使用AI分數)",
        "5 — Excellent",
        "4 — Very Good",
        "3 — Good",
        "2 — Fair",
        "1 — Fail",
        "0 — Missing",
    ]
    SCORE_VALUES = {"5 — Excellent": "5", "4 — Very Good": "4", "3 — Good": "3",
                    "2 — Fair": "2", "1 — Fail": "1", "0 — Missing": "0"}

    for idx, rec in enumerate(filtered):
        sid = rec.get("student_id","")
        name = rec.get("name","")
        week = rec.get("week","")
        ai_score = str(rec.get("ai_score",""))
        final_score = str(rec.get("final_score","")).strip()
        justification = rec.get("ai_justification","")
        released = str(rec.get("released","")).lower() in ("true","1","yes")
        needs_review = str(rec.get("needs_review","")).lower() in ("true","1")
        scan_only = str(rec.get("scan_only","")).lower() in ("true","1")
        is_late = str(rec.get("is_late","")).lower() in ("true","1")
        storage_path = rec.get("storage_path","") or rec.get("drive_url","")
        orig_name = rec.get("original_filename") or rec.get("filename","submission.pdf")
        file_size = rec.get("file_size_bytes","")

        flags = []
        if needs_review: flags.append("⚠️")
        if scan_only:    flags.append("📄")
        if is_late:      flags.append("📨")
        flags.append("✅" if released else "🔒")
        flag_str = " ".join(flags)

        display_score = final_score if final_score else ai_score
        header = f"{flag_str}  {sid} — {name}  |  Week {week}  |  Score: {display_score}/5"

        with st.expander(header):
            # PDF 連結
            size_str = f"{round(int(file_size)/1024, 1)} KB" if str(file_size).isdigit() else ""
            if storage_path and not storage_path.startswith("sheets://"):
                signed_url = storage.get_pdf_signed_url(storage_path, expires_in=3600)
                if signed_url:
                    st.link_button(f"📄 View / Download PDF {size_str}", signed_url)
                    st.caption(f"Original filename / 原始檔名：{orig_name}  {size_str}")
                else:
                    st.caption("Could not generate PDF link.")
            else:
                st.caption("PDF not available.")

            st.markdown(f"**AI Score / AI 分數：** {ai_score} / 5")

            if scan_only:
                st.warning("📄 Scanned PDF — AI could not read text. Please grade manually.")
            if needs_review:
                st.warning("⚠️ This submission requires manual review.")

            # 評語編輯：預設顯示老師已改的版本，沒改過則顯示AI原始評語
            ai_just = rec.get("ai_justification", "")
            teacher_just = rec.get("teacher_justification", "").strip()
            restore_key = f"restore_val_{idx}"

            # 還原按鈕按下時，把 AI 原始評語存入 restore_key
            if st.button("↩️ Restore AI original / 還原AI原始評語", key=f"restore_{idx}"):
                st.session_state[restore_key] = ai_just

            # 預設值優先序：還原值 > 老師已儲存的評語 > AI 原始評語
            default_just = st.session_state.get(restore_key, teacher_just if teacher_just else ai_just)

            st.markdown("**Feedback / 評語（可直接編輯）：**")
            st.caption("Modify as needed. Click 'Restore' above to recover original AI feedback. / 可直接修改，按上方還原鍵可恢復AI原始評語。")
            edited_justification = st.text_area(
                "Edit feedback / 編輯評語",
                value=default_just,
                height=120,
                key=f"just_{idx}"
            )

            # 覆蓋分數
            current_idx = 0
            for i, opt in enumerate(SCORE_OPTIONS):
                if final_score and opt.startswith(final_score):
                    current_idx = i
                    break
            new_score_label = st.selectbox(
                "Override score / 老師最終分數",
                SCORE_OPTIONS,
                index=current_idx,
                key=f"score_{idx}"
            )

            release_toggle = st.checkbox(
                "Release grade to student / 公開成績給學生",
                value=released,
                key=f"release_{idx}"
            )

            if st.button("💾 Save / 儲存", key=f"save_{idx}"):
                final = "" if new_score_label.startswith("(") else SCORE_VALUES.get(new_score_label, "")
                with st.spinner("Saving... / 儲存中..."):
                    storage.update_record(sid, week, semester, {
                        "final_score": final,
                        "teacher_justification": edited_justification,
                        "released": str(release_toggle),
                    })
                st.success("✅ Saved! / 已儲存！")
                st.rerun()
