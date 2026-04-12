"""
admin_grading.py — 批改管理分頁
含：評語編輯、PDF 下載、批量下載整週、手動觸發 AI 評分
四維度分數顯示（A/B/C/D 分數條 + Grade Badge）
"""

import re
import streamlit as st
import zipfile
import io
import requests
import time
import storage
import grader
import pdf_reader


# ─────────────────────────────────────────────
# 四維度顯示 helpers
# ─────────────────────────────────────────────

GRADE_COLOR = {
    "Excellent": "#FFD700",
    "Very Good": "#28a745",
    "Good":      "#007bff",
    "Fair":      "#fd7e14",
}
GRADE_EMOJI = {
    "Excellent": "🌟",
    "Very Good": "✅",
    "Good":      "👍",
    "Fair":      "⚠️",
}
LANG_BADGE = {
    "english_compliant":     ("✅ English", "#28a745"),
    "mixed":                 ("🟡 Mixed",   "#fd7e14"),
    "chinese_dominant":      ("🔴 Chinese", "#dc3545"),
    # 舊版欄位值相容
    "Chinese-dominant":      ("🔴 Chinese", "#dc3545"),
    "Mixed but acceptable":  ("🟡 Mixed",   "#fd7e14"),
}


def _parse_justification(text: str):
    """
    從 ai_justification 字串解析等級、加權分、四維度分數。
    新版格式（grader.py 校正版產出）：
      "Grade: Very Good (Weighted Score: 3.8/5.0) | A-Prompt Strategy: 4/5 |
       B-Knowledge Restructuring: 3/5 | C-Learning Value: 4/5 | D-Personal Trace: 3/5 | ..."
    舊版格式（純文字評語）：解析失敗，回傳 None。
    """
    grade_str, weighted, a, b, c, d = None, None, 0, 0, 0, 0
    if not text:
        return grade_str, weighted, a, b, c, d
    try:
        m = re.search(r"Grade:\s*([\w\s]+?)\s*\(Weighted Score:\s*([\d.]+)", text)
        if m:
            grade_str = m.group(1).strip()
            weighted  = float(m.group(2))
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


def _show_grade_badge(grade_str: str, weighted):
    color        = GRADE_COLOR.get(grade_str, "#aaa")
    emoji        = GRADE_EMOJI.get(grade_str, "")
    weighted_str = f"{weighted}/5.0" if weighted is not None else "—"
    st.markdown(
        f"<div style='background:{color}22; border-left:4px solid {color}; "
        f"padding:6px 12px; border-radius:6px; margin:6px 0;'>"
        f"<b style='font-size:1.05em'>{emoji} {grade_str}</b>"
        f"&nbsp;&nbsp;<span style='color:#555; font-size:0.9em'>"
        f"Weighted: <b>{weighted_str}</b></span></div>",
        unsafe_allow_html=True,
    )


def _show_dim_bars(a: int, b: int, c: int, d: int):
    dims = [
        ("A Prompt",        a, "#6c63ff"),
        ("B Restructuring", b, "#17a2b8"),
        ("C Value",         c, "#28a745"),
        ("D Trace",         d, "#fd7e14"),
    ]
    cols = st.columns(4)
    for col, (label, score, bar_color) in zip(cols, dims):
        if score == 0:
            continue
        pct = int(score / 5 * 100)
        with col:
            st.markdown(
                f"<div style='font-size:0.78em; color:#555; margin-bottom:2px'>{label}</div>"
                f"<div style='background:#e9ecef; border-radius:4px; height:7px; margin-bottom:3px'>"
                f"<div style='background:{bar_color}; width:{pct}%; height:7px; border-radius:4px'></div></div>"
                f"<div style='font-size:0.88em; font-weight:600'>{score}/5</div>",
                unsafe_allow_html=True,
            )


def _show_lang_badge(lang_compliance: str):
    if not lang_compliance:
        return
    badge_text, badge_color = LANG_BADGE.get(lang_compliance, (lang_compliance, "#aaa"))
    st.markdown(
        f"<span style='background:{badge_color}22; color:{badge_color}; "
        f"border:1px solid {badge_color}44; border-radius:4px; "
        f"padding:2px 8px; font-size:0.82em'>{badge_text}</span>",
        unsafe_allow_html=True,
    )


def _show_ai_result(ai_just: str, lang_compliance: str):
    """
    新版格式 → Grade badge + 四維度分數條 + 折疊評語
    舊版格式 → 直接顯示文字評語
    """
    grade_str, weighted, a, b, c, d = _parse_justification(ai_just)

    if grade_str:
        _show_grade_badge(grade_str, weighted)
        if any([a, b, c, d]):
            _show_dim_bars(a, b, c, d)
        _show_lang_badge(lang_compliance)
        with st.expander("📝 Full AI feedback / 完整AI評語"):
            st.caption(ai_just)
    else:
        _show_lang_badge(lang_compliance)
        st.info(ai_just)


# ─────────────────────────────────────────────
# 主要 render 函式
# ─────────────────────────────────────────────

def render(semester: str):
    st.subheader("Grading / 批改管理")

    if not semester:
        st.info("Please set the current semester in Settings first.")
        return

    if st.button("🔄 Refresh data / 重新整理資料", key="grading_refresh"):
        st.cache_data.clear()
        st.rerun()

    records = storage.load_all_records(semester)
    if not records:
        st.info("No submissions yet.")
        return

    # ── 篩選列 ────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        all_weeks   = sorted({str(r.get("week", "")) for r in records})
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
        RETRIABLE_STATUSES = {"rate_limit", "failed", "parse_error", ""}
        ungrated = [
            r for r in filtered
            if str(r.get("scan_only","")).lower() not in ("true","1")
            and (
                not str(r.get("ai_score","")).strip()
                or str(r.get("ai_request_status","")).strip() in RETRIABLE_STATUSES
            )
            and str(r.get("ai_request_status","")).strip() != "success"
        ]
        if ungrated:
            st.caption(
                f"⚠️ {len(ungrated)} pending/failed — 7s interval to avoid quota limits. / "
                f"待評分或失敗可重跑，每筆間隔7秒。"
            )
            if st.button(f"🤖 Run AI grading ({len(ungrated)}) / 批量AI評分"):
                progress = st.progress(0, text="Starting AI grading... / 開始AI評分...")
                success_count, failed_count = 0, 0
                fail_reasons = []
                BATCH_INTERVAL = 7
                active_model = grader.FIXED_MODEL
                for i, rec in enumerate(ungrated):
                    sid          = rec.get("student_id","")
                    week         = rec.get("week","")
                    path         = rec.get("storage_path","")
                    week_config  = storage.get_week_config(semester, week)
                    key_concepts = week_config.get("key_concepts","") if week_config else ""
                    progress.progress(
                        (i+1)/len(ungrated),
                        text=f"Grading {i+1}/{len(ungrated)}: {sid} Week {week} / 評分中..."
                    )
                    try:
                        signed_url = storage.get_pdf_signed_url(path, expires_in=300) if path else None
                        if not signed_url:
                            storage.update_record(sid, week, semester, {
                                "ai_request_status": "failed",
                                "ai_justification":  "Could not generate PDF URL.",
                                "needs_review":      "True",
                            })
                            failed_count += 1
                            fail_reasons.append(f"{sid} W{week}: no PDF URL")
                            continue
                        resp = requests.get(signed_url, timeout=30)
                        if resp.status_code != 200:
                            storage.update_record(sid, week, semester, {
                                "ai_request_status": "failed",
                                "ai_justification":  f"PDF download failed (HTTP {resp.status_code}).",
                                "needs_review":      "True",
                            })
                            failed_count += 1
                            fail_reasons.append(f"{sid} W{week}: HTTP {resp.status_code}")
                            continue
                        text, err = pdf_reader.extract_text_from_bytes(resp.content)
                        if err or not text.strip():
                            storage.update_record(sid, week, semester, {
                                "scan_only":         "True",
                                "needs_review":      "True",
                                "ai_justification":  "PDF could not be read. Manual review required.",
                                "ai_request_status": "scan_only",
                                "ai_model":          active_model,
                            })
                            success_count += 1
                            continue
                        sc, just, nr, log = grader.grade(text, key_concepts)
                        storage.update_record(sid, week, semester, {
                            "ai_score":              str(sc),
                            "ai_justification":      just,
                            "needs_review":          str(nr),
                            "teacher_justification": "",
                            "ai_model":              log["model_name"],
                            "ai_graded_at":          log["graded_at"],
                            "ai_retry_count":        str(log["retry_count"]),
                            "ai_request_status":     log["request_status"],
                            "ai_input_tokens_est":   str(log["input_tokens_est"]),
                            "language_compliance":   log.get("language_compliance", ""),
                        })
                        if log["request_status"] == "success":
                            success_count += 1
                        else:
                            failed_count += 1
                            fail_reasons.append(f"{sid} W{week}: {log['request_status']}")
                    except Exception as e:
                        storage.update_record(sid, week, semester, {
                            "ai_request_status": "failed",
                            "ai_justification":  f"Unexpected error: {str(e)[:120]}",
                            "needs_review":      "True",
                        })
                        failed_count += 1
                        fail_reasons.append(f"{sid} W{week}: exception")
                    if i < len(ungrated) - 1:
                        time.sleep(BATCH_INTERVAL)
                progress.empty()
                st.success(
                    f"✅ Done: {success_count} success, {failed_count} failed. / "
                    f"完成：{success_count} 成功，{failed_count} 失敗。"
                )
                if fail_reasons:
                    st.warning("Failed records / 失敗紀錄：\n" + "\n".join(fail_reasons))
                st.rerun()

    with col_c:
        if week_filter != "All":
            week_records = [r for r in filtered if r.get("storage_path","")]
            if week_records:
                if st.button(f"📦 Download all PDFs Week {week_filter} / 批量下載PDF"):
                    with st.spinner("Preparing ZIP... / 打包中..."):
                        zip_buffer    = io.BytesIO()
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
                                        fname = rec.get("original_filename") or \
                                                f"{rec['student_id']}_Week{week_filter}.pdf"
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
    SCORE_VALUES = {
        "5 — Excellent": "5", "4 — Very Good": "4", "3 — Good": "3",
        "2 — Fair": "2",      "1 — Fail": "1",      "0 — Missing": "0",
    }

    for idx, rec in enumerate(filtered):
        sid             = rec.get("student_id","")
        name            = rec.get("name","")
        week            = rec.get("week","")
        ai_score        = str(rec.get("ai_score","")).strip()
        final_score     = str(rec.get("final_score","")).strip()
        ai_just         = str(rec.get("ai_justification","")).strip()
        teacher_just    = str(rec.get("teacher_justification","")).strip()
        lang_compliance = str(rec.get("language_compliance","")).strip()
        released        = str(rec.get("released","")).lower() in ("true","1","yes")
        needs_review    = str(rec.get("needs_review","")).lower() in ("true","1")
        scan_only       = str(rec.get("scan_only","")).lower() in ("true","1")
        is_late         = str(rec.get("is_late","")).lower() in ("true","1")
        storage_path    = rec.get("storage_path","") or rec.get("drive_url","")
        orig_name       = rec.get("original_filename") or rec.get("filename","submission.pdf")
        file_size       = rec.get("file_size_bytes","")

        flags = []
        if needs_review: flags.append("⚠️")
        if scan_only:    flags.append("📄")
        if is_late:      flags.append("📨")
        flags.append("✅" if released else "🔒")
        flag_str = " ".join(flags)

        display_score = final_score if final_score else (ai_score if ai_score else "?")
        header = f"{flag_str}  {sid} — {name}  |  Week {week}  |  Score: {display_score}/5"

        with st.expander(header):

            # ── PDF 連結 ──────────────────────────────────────
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

            # ── AI 分數 + 單筆評分按鈕 ────────────────────────
            score_col, btn_col = st.columns([3, 2])
            with score_col:
                st.markdown(
                    f"**AI Score / AI 分數：** {ai_score if ai_score else '（尚未評分）'} / 5"
                )
            with btn_col:
                if not scan_only:
                    if st.button("🤖 Run AI now / 立即AI評分", key=f"ai_now_{idx}"):
                        with st.spinner("AI grading... / AI評分中..."):
                            active_model = grader.FIXED_MODEL
                            week_config  = storage.get_week_config(semester, week)
                            key_concepts = week_config.get("key_concepts","") if week_config else ""
                            try:
                                signed    = storage.get_pdf_signed_url(storage_path, expires_in=300)
                                resp      = requests.get(signed, timeout=30)
                                text, err = pdf_reader.extract_text_from_bytes(resp.content)
                                if err or not text.strip():
                                    storage.update_record(sid, week, semester, {
                                        "scan_only":             "True",
                                        "needs_review":          "True",
                                        "ai_justification":      "PDF could not be read. Manual review required.",
                                        "teacher_justification": "",
                                        "ai_request_status":     "scan_only",
                                        "ai_model":              active_model,
                                    })
                                    st.warning("Scanned PDF detected.")
                                else:
                                    sc, just, nr, log = grader.grade(text, key_concepts)
                                    storage.update_record(sid, week, semester, {
                                        "ai_score":              str(sc),
                                        "ai_justification":      just,
                                        "needs_review":          str(nr),
                                        "teacher_justification": "",
                                        "ai_model":              log["model_name"],
                                        "ai_graded_at":          log["graded_at"],
                                        "ai_retry_count":        str(log["retry_count"]),
                                        "ai_request_status":     log["request_status"],
                                        "ai_input_tokens_est":   str(log["input_tokens_est"]),
                                        "language_compliance":   log.get("language_compliance", ""),
                                    })
                                    if log["request_status"] == "success":
                                        st.success(f"AI score: {sc}/5  (model: {log['model_name']})")
                                    else:
                                        st.error(f"AI grading failed ({log['request_status']}): {just}")
                            except Exception as e:
                                st.error(f"AI grading failed: {e}")
                        if f"just_{sid}_{week}" in st.session_state:
                            del st.session_state[f"just_{sid}_{week}"]
                        st.rerun()

            # ── 警告標記 ──────────────────────────────────────
            if scan_only:
                st.warning("📄 Scanned PDF — AI could not read text. Please grade manually.")
            if needs_review:
                st.warning("⚠️ This submission requires manual review.")

            # ── AI 評分結果 ───────────────────────────────────
            st.markdown("**AI Feedback / AI 評語（唯讀）：**")
            if ai_just:
                _show_ai_result(ai_just, lang_compliance)
            else:
                st.caption("（尚未AI評分 / Not yet graded by AI）")
                _show_lang_badge(lang_compliance)

            # ── 老師編輯區 ────────────────────────────────────
            st.markdown(
                "**Teacher Feedback / 老師評語（可編輯，留空則對學生顯示AI評語）：**"
            )
            st.caption(
                "Leave blank to show AI feedback to student. Fill in to override. / "
                "留空則學生看到AI評語，填寫後學生看到老師評語。"
            )
            edited_justification = st.text_area(
                "Edit feedback / 編輯評語",
                value=teacher_just,
                height=120,
                key=f"just_{sid}_{week}",
            )

            # ── 覆蓋分數 ──────────────────────────────────────
            current_idx = 0
            for i, opt in enumerate(SCORE_OPTIONS):
                if final_score and opt.startswith(final_score):
                    current_idx = i
                    break
            new_score_label = st.selectbox(
                "Override score / 老師最終分數",
                SCORE_OPTIONS,
                index=current_idx,
                key=f"score_{sid}_{week}",
            )

            release_toggle = st.checkbox(
                "Release grade to student / 公開成績給學生",
                value=released,
                key=f"release_{sid}_{week}",
            )

            if st.button("💾 Save / 儲存", key=f"save_{idx}"):
                final = "" if new_score_label.startswith("(") else SCORE_VALUES.get(new_score_label, "")
                with st.spinner("Saving... / 儲存中..."):
                    storage.update_record(sid, week, semester, {
                        "final_score":           final,
                        "teacher_justification": edited_justification,
                        "released":              str(release_toggle),
                    })
                st.success("✅ Saved! / 已儲存！")
                st.rerun()
