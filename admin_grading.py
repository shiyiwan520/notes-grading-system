"""
admin_grading.py — 批改管理分頁
含：評語編輯、PDF 下載、批量下載整週、手動觸發 AI 評分
"""

import streamlit as st
import zipfile
import io
import requests
import time
import storage
import grader
import pdf_reader


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
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("✅ Release all filtered / 批量公開篩選成績"):
            for r in filtered:
                if str(r.get("released","")).lower() not in ("true","1"):
                    storage.update_record(r["student_id"], r["week"], semester, {"released": "True"})
            st.success(f"Released {len(filtered)} grades.")
            st.rerun()

    with col_b:
        # 批量 AI 評分（手動模式下使用）
        ungrated = [r for r in filtered
                    if not str(r.get("ai_score","")).strip()
                    and not str(r.get("scan_only","")).lower() in ("true","1")]
        if ungrated:
            st.caption(f"⚠️ {len(ungrated)} ungraded — will run one by one with 7s interval to avoid quota limits. / 將逐筆評分，每筆間隔7秒避免超過API限制。")
            if st.button(f"🤖 Run AI grading ({len(ungrated)}) / 批量AI評分"):
                progress = st.progress(0, text="Starting AI grading... / 開始AI評分...")
                success, failed = 0, 0
                BATCH_INTERVAL = 7  # 秒，保守低於 RPM 10 的限制
                for i, rec in enumerate(ungrated):
                    sid = rec.get("student_id","")
                    week = rec.get("week","")
                    path = rec.get("storage_path","")
                    week_config = storage.get_week_config(semester, week)
                    key_concepts = week_config.get("key_concepts","") if week_config else ""
                    progress.progress(
                        (i+1)/len(ungrated),
                        text=f"Grading {i+1}/{len(ungrated)}: {sid} Week {week} / 評分中..."
                    )
                    try:
                        signed_url = storage.get_pdf_signed_url(path, expires_in=300) if path else None
                        if signed_url:
                            resp = requests.get(signed_url, timeout=30)
                            if resp.status_code == 200:
                                text, err = pdf_reader.extract_text_from_bytes(resp.content)
                                if err or not text.strip():
                                    storage.update_record(sid, week, semester, {
                                        "scan_only": "True", "needs_review": "True",
                                        "ai_justification": "PDF could not be read. Manual review required.",
                                        "teacher_justification": "",
                                        "ai_request_status": "failed",
                                        "ai_model": grader.DEFAULT_MODEL,
                                    })
                                else:
                                    score, justification, needs_review, log = grader.grade(text, key_concepts)
                                    storage.update_record(sid, week, semester, {
                                        "ai_score": str(score),
                                        "ai_justification": justification,
                                        "needs_review": str(needs_review),
                                        "teacher_justification": "",
                                        "ai_model": log["model_name"],
                                        "ai_graded_at": log["graded_at"],
                                        "ai_retry_count": str(log["retry_count"]),
                                        "ai_request_status": log["request_status"],
                                        "ai_input_tokens_est": str(log["input_tokens_est"]),
                                    })
                                success += 1
                            else:
                                failed += 1
                        else:
                            failed += 1
                    except Exception as e:
                        failed += 1
                    # 每筆之間等待，除非是最後一筆
                    if i < len(ungrated) - 1:
                        time.sleep(BATCH_INTERVAL)
                progress.empty()
                st.success(f"✅ AI grading done: {success} success, {failed} failed. / 完成：{success} 成功，{failed} 失敗。")
                st.rerun()

    with col_c:
        # 批量下載整週 PDF
        if week_filter != "All":
            week_records = [r for r in filtered if r.get("storage_path","")]
            if week_records:
                if st.button(f"📦 Download all PDFs Week {week_filter} / 批量下載PDF"):
                    with st.spinner("Preparing ZIP... / 打包中..."):
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
                            f"📥 Download ZIP ({success_count} files)",
                            data=zip_buffer,
                            file_name=f"{semester}_Week{week_filter}_PDFs.zip",
                            mime="application/zip"
                        )
                    else:
                        st.error("Could not download any PDFs.")

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
        ai_score = str(rec.get("ai_score","")).strip()
        final_score = str(rec.get("final_score","")).strip()
        ai_just = str(rec.get("ai_justification","")).strip()
        teacher_just = str(rec.get("teacher_justification","")).strip()
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

        display_score = final_score if final_score else (ai_score if ai_score else "?")
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

            # AI 分數 + 單筆 AI 評分按鈕
            score_col, btn_col = st.columns([3, 2])
            with score_col:
                st.markdown(f"**AI Score / AI 分數：** {ai_score if ai_score else '（尚未評分）'} / 5")
            with btn_col:
                if not scan_only:
                    if st.button("🤖 Run AI now / 立即AI評分", key=f"ai_now_{idx}"):
                        with st.spinner("AI grading... / AI評分中..."):
                            path = storage_path
                            week_config = storage.get_week_config(semester, week)
                            key_concepts = week_config.get("key_concepts","") if week_config else ""
                            try:
                                signed = storage.get_pdf_signed_url(path, expires_in=300)
                                resp = requests.get(signed, timeout=30)
                                text, err = pdf_reader.extract_text_from_bytes(resp.content)
                                if err or not text.strip():
                                    storage.update_record(sid, week, semester, {
                                        "scan_only": "True", "needs_review": "True",
                                        "ai_justification": "PDF could not be read. Manual review required.",
                                        "teacher_justification": "",  # 清空，顯示最新AI結果
                                    })
                                    st.warning("Scanned PDF detected.")
                                else:
                                    sc, just, nr, log = grader.grade(text, key_concepts)
                                    storage.update_record(sid, week, semester, {
                                        "ai_score": str(sc),
                                        "ai_justification": just,
                                        "needs_review": str(nr),
                                        "teacher_justification": "",
                                        "ai_model": log["model_name"],
                                        "ai_graded_at": log["graded_at"],
                                        "ai_retry_count": str(log["retry_count"]),
                                        "ai_request_status": log["request_status"],
                                        "ai_input_tokens_est": str(log["input_tokens_est"]),
                                    })
                                    st.success(f"AI score: {sc}/5")
                            except Exception as e:
                                st.error(f"AI grading failed: {e}")
                        # 清掉 text_area session_state，讓新的 ai_justification 能正確顯示
                        if f"just_{sid}_{week}" in st.session_state:
                            del st.session_state[f"just_{sid}_{week}"]
                        st.rerun()

            if scan_only:
                st.warning("📄 Scanned PDF — AI could not read text. Please grade manually.")
            if needs_review:
                st.warning("⚠️ This submission requires manual review.")

            # ── 評語區 ────────────────────────────────────────
            # AI 評語：唯讀，永遠顯示最新的 ai_justification
            st.markdown("**AI Feedback / AI 評語（唯讀）：**")
            if ai_just:
                st.info(ai_just)
            else:
                st.caption("（尚未AI評分 / Not yet graded by AI）")

            # 老師編輯區：預設空白，老師參考上方AI評語後自行填寫
            st.markdown("**Teacher Feedback / 老師評語（可編輯，留空則對學生顯示AI評語）：**")
            st.caption("Leave blank to show AI feedback to student. Fill in to override. / 留空則學生看到AI評語，填寫後學生看到老師評語。")
            textarea_key = f"just_{sid}_{week}"
            edited_justification = st.text_area(
                "Edit feedback / 編輯評語",
                value=teacher_just,
                height=120,
                key=textarea_key
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
                key=f"score_{sid}_{week}"
            )

            release_toggle = st.checkbox(
                "Release grade to student / 公開成績給學生",
                value=released,
                key=f"release_{sid}_{week}"
            )

            if st.button("💾 Save / 儲存", key=f"save_{idx}"):
                final = "" if new_score_label.startswith("(") else SCORE_VALUES.get(new_score_label, "")
                # 儲存後清除還原狀態
                if restore_key in st.session_state:
                    del st.session_state[restore_key]
                with st.spinner("Saving... / 儲存中..."):
                    storage.update_record(sid, week, semester, {
                        "final_score": final,
                        "teacher_justification": edited_justification,
                        "released": str(release_toggle),
                    })
                st.success("✅ Saved! / 已儲存！")
                st.rerun()
