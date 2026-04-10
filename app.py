"""
app.py — 英文筆記繳交與 AI 輔助評分系統
English Notes Submission & AI Grading System
"""

import streamlit as st
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv

import storage
import grader
import pdf_reader
import notifications

load_dotenv()
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "changeme"))

# ── 頁面設定 ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Notes Submission System / 筆記繳交系統",
    page_icon="📝",
    layout="centered"
)

if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False
# overwrite_ready: 第一次按 Submit 發現重複時設為 True，第二次按就直接覆蓋
if "overwrite_ready" not in st.session_state:
    st.session_state.overwrite_ready = False
# overwrite_week: 記住是哪一週觸發了覆蓋確認（避免換週次後誤觸）
if "overwrite_week" not in st.session_state:
    st.session_state.overwrite_week = None

# ── 側邊欄導覽 ────────────────────────────────────────────────
st.sidebar.title("📝 Navigation / 導覽")
page = st.sidebar.radio(
    "Select / 選擇",
    ["📤 Submit Notes / 繳交作業", "🔍 Check Grade / 查詢成績", "🔐 Teacher Admin / 老師後台"]
)

# ════════════════════════════════════════════════════════════════
#  公告欄（顯示在學生頁面頂部）
# ════════════════════════════════════════════════════════════════
def show_announcements():
    announcements = storage.get_announcements()
    if announcements:
        for ann in announcements:
            st.info(f"📢 {ann['content']}  \n*{ann['posted_at']}*")

# ════════════════════════════════════════════════════════════════
#  共用函式：繳交處理（必須在 if/elif 之前定義）
# ════════════════════════════════════════════════════════════════
def _process_submission(student_id, student_name, week, semester, uploaded_file, is_late=False):
    """
    安全繳交流程：
    1. 大小驗證  2. 上傳 Supabase  3. AI 評分  4. 寫 Sheets  5. 刪舊檔  6. 顯示成功
    任一步驟失敗都停止，不顯示假成功。
    重複繳交：第一次按 Submit 顯示警告（overwrite_ready=True），第二次按直接覆蓋。
    """
    existing = storage.find_record(student_id, week, semester)

    # 若成績已公開 → 鎖定，不允許再繳交
    if existing and str(existing.get("released","")).lower() in ("true","1","yes"):
        st.error(
            "Your grade for Week " + str(week) + " has already been released. "
            "Resubmission is not allowed after grading is complete.\n"
            "您本週的成績已公開，批改完成後不允許再次繳交。"
        )
        return

    # 若已有紀錄且這是「第一次」按 Submit（尚未確認覆蓋）→ 顯示警告，記住 flag，停止
    if existing and not (st.session_state.overwrite_ready and st.session_state.overwrite_week == week):
        st.session_state.overwrite_ready = True
        st.session_state.overwrite_week = week
        st.warning(
            "⚠️ You have already submitted for Week " + str(week) + ". "
            "**Click Submit again to confirm replacing your previous submission.**\n\n"
            "您本週已有繳交紀錄。**請再按一次「繳交」按鈕，即可覆蓋舊作業。**"
        )
        return  # 停止。下次按 Submit，overwrite_ready==True，直接通過

    # 第二次按到這裡：重置 flag，繼續正常流程
    st.session_state.overwrite_ready = False
    st.session_state.overwrite_week = None

    # 步驟1：讀取並驗證檔案大小
    pdf_bytes = uploaded_file.read()
    file_size = len(pdf_bytes)
    if file_size > storage.MAX_FILE_SIZE_BYTES:
        size_mb = round(file_size / (1024 * 1024), 2)
        st.error(
            "File too large (" + str(size_mb) + " MB). Maximum allowed size is 5 MB. "
            "Please compress your PDF before uploading.\n"
            "檔案過大（" + str(size_mb) + " MB），上限為 5 MB。"
            "請先壓縮 PDF 後再重新上傳。建議保留清晰可閱讀的內容即可，不需要高解析圖片。"
        )
        return

    # 步驟2：上傳 PDF 到 Supabase
    with st.spinner("Uploading PDF... / 上傳檔案中，請稍候..."):
        old_path = existing.get("storage_path", "") if existing else ""
        upload_result = storage.upload_pdf(
            pdf_bytes=pdf_bytes,
            original_filename=uploaded_file.name,
            student_id=student_id,
            student_name=student_name,
            semester=semester,
            week=week,
        )

    if not upload_result["success"]:
        st.error(
            "File upload failed. Your submission has NOT been recorded. Please try again.\n"
            "檔案上傳失敗，您的作業尚未繳交，請稍後再試。"
        )
        return

    # 步驟3：讀取文字 + AI 評分
    with st.spinner("AI is grading your notes... / AI 評分中，請稍候..."):
        text, read_error = pdf_reader.extract_text_from_bytes(pdf_bytes)
        week_config = storage.get_week_config(semester, week)
        key_concepts = week_config.get("key_concepts", "") if week_config else ""
        if read_error or not text.strip():
            score, justification, needs_review = (
                0, "PDF could not be read (possibly scanned image). Manual review required.", True
            )
            scan_flag = True
        else:
            score, justification, needs_review = grader.grade(text, key_concepts)
            scan_flag = False

    # 步驟4：寫入 Google Sheets
    tw_tz = timezone(timedelta(hours=8))
    submitted_at = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "semester": semester,
        "student_id": student_id,
        "name": student_name,
        "week": week,
        "original_filename": uploaded_file.name,
        "file_size_bytes": file_size,
        "storage_bucket": storage.SUPABASE_BUCKET,
        "storage_path": upload_result["storage_path"],
        "file_url": upload_result["file_url"],
        "replaced_previous": bool(existing),
        "ai_score": score,
        "ai_justification": justification,
        "needs_review": needs_review,
        "scan_only": scan_flag,
        "is_late": is_late,
        "final_score": "",
        "released": False,
        "submitted_at": submitted_at,
    }

    with st.spinner("Saving submission record... / 儲存繳交紀錄中..."):
        try:
            storage.save_record(record, overwrite=bool(existing))
        except Exception as e:
            storage.delete_old_pdf(upload_result["storage_path"])
            st.error(
                "Failed to save your submission record. The uploaded file has been removed. Please try again.\n"
                "繳交紀錄儲存失敗，已自動清除上傳的檔案，請稍後再試。"
            )
            return

    # 步驟5：確認 Sheets 寫入後才刪舊檔
    if existing and old_path:
        storage.delete_old_pdf(old_path)

    # 步驟6：顯示真實成功訊息
    if existing:
        st.success(
            "Resubmission successful! Your previous submission has been replaced.\n"
            "重新繳交成功！前一份作業已自動取代。"
        )
    else:
        st.success("Submitted successfully!\n繳交成功！")

    if is_late:
        st.info("This submission is marked as late.\n本次繳交已標記為補交。")
    if scan_flag:
        st.warning(
            "Your PDF appears to be a scanned image. AI grading was not possible — your teacher will grade it manually.\n"
            "您上傳的 PDF 為掃描版圖片，AI 無法自動評分，老師將手動批改。"
        )

    size_kb = round(file_size / 1024, 1)
    st.info(
        f"**Student ID / 學號：** {student_id}  \n"
        f"**Name / 姓名：** {student_name}  \n"
        f"**Week / 週次：** Week {week}  \n"
        f"**File size / 檔案大小：** {size_kb} KB  \n"
        f"**Submitted at / 繳交時間：** {submitted_at}"
    )
    st.markdown(
        "> Grades will be released after the teacher reviews your submission.  \n"
        "> 成績將在老師審閱後公開，請稍後至「Check Grade / 查詢成績」頁面查看。"
    )
    notifications.notify_new_submission(record)


# ════════════════════════════════════════════════════════════════
#  頁面 1：學生繳交作業
# ════════════════════════════════════════════════════════════════
if page == "📤 Submit Notes / 繳交作業":
    show_announcements()
    st.title("📝 English Notes Submission / 英文筆記繳交")
    st.markdown(
        "Please upload your English notes in PDF format.  \n"
        "請上傳您的英文筆記 PDF 檔案。"
    )
    st.info(
        "Only PDF files accepted, maximum **5 MB** per file. "
        "If you resubmit the same week, only the latest submission will be kept.  \n"
        "僅接受 **PDF** 格式，每份檔案大小請控制在 **5 MB** 以內。"
        "若同一週重複提交，系統將以最後一次提交為準。"
    )
    st.divider()

    # ── 取得目前學期與開放週次 ────────────────────────────────
    settings = storage.get_settings()
    current_semester = settings.get("current_semester", "")
    open_weeks = storage.get_open_weeks(current_semester)  # list of {"week": "01", "deadline": ""}

    if not current_semester or not open_weeks:
        st.warning(
            "No weeks are currently open for submission.  \n"
            "目前沒有開放繳交的週次，請稍後再試或聯絡老師。"
        )
        st.stop()

    # ── 建立週次選項（含截止日提示）────────────────────────────
    week_options = []
    now = datetime.now().date()
    for w in open_weeks:
        deadline_str = w.get("deadline", "")
        if deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                if deadline < now:
                    continue  # 已過截止，不顯示（除非補交）
                days_left = (deadline - now).days
                label = f"Week {w['week']}  (Due: {deadline_str}, {days_left} days left / 還有 {days_left} 天)"
            except ValueError:
                label = f"Week {w['week']}"
        else:
            label = f"Week {w['week']}  (No deadline / 無截止期限)"
        week_options.append((label, w["week"]))

    # ── 表單 ──────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        student_id_raw = st.text_input(
            "Student ID / 學號 *",
            placeholder="e.g. M1344022"
        )
        student_id = student_id_raw.strip().upper() if student_id_raw else ""
    with col2:
        student_name = st.text_input(
            "Name / 姓名 *",
            placeholder="e.g. 王小明 / Wang Xiao-Ming"
        )

    # 週次選單
    if week_options:
        week_label = st.selectbox(
            "Week / 週次 *",
            options=[o[0] for o in week_options]
        )
        selected_week = next(o[1] for o in week_options if o[0] == week_label)
    else:
        st.warning("No open weeks available. / 目前無開放週次。")
        st.stop()

    uploaded_file = st.file_uploader(
        "Upload PDF / 上傳 PDF *",
        type=["pdf"]
    )

    # ── 即時學號驗證 ──────────────────────────────────────────
    id_valid = False
    if student_id:
        if student_id_raw.strip() != student_id:
            st.caption(f"ℹ️ Student ID auto-corrected to uppercase / 學號已自動轉為大寫：**{student_id}**")
        students = storage.get_students(current_semester)
        valid_ids = [s["student_id"].upper() for s in students]
        if valid_ids and student_id not in valid_ids:
            st.warning(
                f"⚠️ Student ID **{student_id}** not found in the class list.  \n"
                "學號查無此人，請確認後再試。"
            )
        else:
            id_valid = True

    st.divider()

    # ── 補交申請（截止週次）────────────────────────────────────
    all_weeks = storage.get_all_weeks(current_semester)
    closed_weeks = []
    for w in all_weeks:
        deadline_str = w.get("deadline", "")
        is_open = w.get("open", False)
        if is_open and deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                if deadline < now:
                    closed_weeks.append(w)
            except ValueError:
                pass

    if closed_weeks:
        with st.expander("📨 Late submission request / 補交申請"):
            st.markdown(
                "If the deadline has passed, you may submit a late request here.  \n"
                "若已超過截止日，可在此申請補交，系統將直接受理並標記為補交。"
            )
            late_week_options = [f"Week {w['week']}" for w in closed_weeks]
            late_week_label = st.selectbox("Week / 週次", late_week_options, key="late_week")
            late_week = late_week_label.replace("Week ", "")
            late_file = st.file_uploader("Upload PDF / 上傳 PDF", type=["pdf"], key="late_file")
            late_btn = st.button("Submit Late / 送出補交", key="late_btn")

            if late_btn:
                if not student_id or not id_valid:
                    st.error("Please enter a valid student ID first. / 請先輸入有效學號。")
                elif not student_name.strip():
                    st.error("Please enter your name. / 請輸入姓名。")
                elif not late_file:
                    st.error("Please upload a PDF. / 請上傳 PDF。")
                else:
                    _process_submission(
                        student_id, student_name.strip(), late_week,
                        current_semester, late_file, is_late=True
                    )

    # ── 正式繳交按鈕 ──────────────────────────────────────────
    # 若目前處於「等待覆蓋確認」狀態，按鈕文字改變，提醒用戶再按一次即可覆蓋
    is_overwrite_pending = (
        st.session_state.overwrite_ready and
        st.session_state.overwrite_week == selected_week
    )
    btn_label = "📤 Submit again to confirm / 再按一次確認覆蓋" if is_overwrite_pending else "📤 Submit / 繳交"
    submit_btn = st.button(btn_label, type="primary", use_container_width=True)

    if submit_btn:
        errors = []
        if not student_id:
            errors.append("Please enter your Student ID. / 請輸入學號。")
        elif not id_valid:
            errors.append("Student ID not found. / 學號查無此人。")
        if not student_name.strip():
            errors.append("Please enter your name. / 請輸入姓名。")
        if not uploaded_file:
            errors.append("Please upload a PDF file. / 請上傳 PDF 檔案。")

        if errors:
            for e in errors:
                st.error(e)
        else:
            _process_submission(
                student_id, student_name.strip(), selected_week,
                current_semester, uploaded_file, is_late=False
            )





# ════════════════════════════════════════════════════════════════
#  頁面 2：查詢成績
# ════════════════════════════════════════════════════════════════
elif page == "🔍 Check Grade / 查詢成績":
    show_announcements()
    st.title("🔍 Check Your Grade / 查詢成績")
    st.markdown(
        "Enter your Student ID to check your grades.  \n"
        "輸入學號查詢成績。"
    )
    st.divider()

    settings = storage.get_settings()
    current_semester = settings.get("current_semester", "")

    q_id = st.text_input(
        "Student ID / 學號",
        placeholder="e.g. M1344022"
    ).strip().upper()

    q_passcode = st.text_input(
        "Passcode / 驗證碼（if set / 若有設定）",
        placeholder="Leave blank if not set / 未設定請留空",
        type="password"
    ).strip()

    if st.button("Search / 查詢", type="primary"):
        if not q_id:
            st.warning("Please enter your Student ID. / 請輸入學號。")
        else:
            # 驗證碼檢查
            students = storage.get_students(current_semester)
            student_info = next(
                (s for s in students if s.get("student_id", "").upper() == q_id),
                None
            )
            stored_passcode = str(student_info.get("passcode", "")).strip().lstrip("'") if student_info else ""

            if stored_passcode and q_passcode != stored_passcode:
                st.error(
                    "Incorrect passcode. / 驗證碼錯誤，請確認後再試。"
                )
                st.stop()

            records = storage.find_all_records_for_student(q_id, current_semester)
            if not records:
                st.error(
                    "No submissions found for this Student ID.  \n"
                    "查無此學號的繳交紀錄。"
                )
            else:
                st.success(f"Found {len(records)} submission(s). / 找到 {len(records)} 筆紀錄。")
                for rec in sorted(records, key=lambda x: x.get("week", "")):
                    week = rec.get("week", "?")
                    released = str(rec.get("released", "")).lower() in ("true", "1", "yes")
                    is_late = str(rec.get("is_late", "")).lower() in ("true", "1", "yes")
                    late_tag = "  📨 Late / 補交" if is_late else ""

                    with st.expander(f"Week {week}{late_tag}  —  {'Grade released / 成績已公開 ✅' if released else 'Pending / 待公開 🔒'}"):
                        orig_name = rec.get("original_filename") or rec.get("filename","")
                        file_size = rec.get("file_size_bytes","")
                        size_str = f"{round(int(file_size)/1024, 1)} KB" if str(file_size).isdigit() else ""
                        st.markdown(f"**Submitted at / 繳交時間：** {rec.get('submitted_at', '')}")
                        if orig_name:
                            st.markdown(f"**File / 檔案：** {orig_name}  {size_str}")
                        if str(rec.get("replaced_previous","")).lower() in ("true","1"):
                            st.caption("This is a resubmission. / 本次為重新繳交。")
                        if released:
                            final = rec.get("final_score") or rec.get("ai_score")
                            st.markdown(f"**Grade / 成績：** {final} / 5")
                            # 顯示老師評語優先，沒有才顯示 AI 評語
                            feedback = rec.get("teacher_justification","").strip() or rec.get("ai_justification","")
                            st.markdown(f"**Feedback / 評語：**  \n{feedback}")
                        else:
                            st.info(
                                "Your grade is not yet released. Please check back later.  \n"
                                "成績尚未公開，請稍後再查。"
                            )


# ════════════════════════════════════════════════════════════════
#  頁面 3：老師管理後台
# ════════════════════════════════════════════════════════════════
elif page == "🔐 Teacher Admin / 老師後台":
    st.title("🔐 Teacher Admin Panel / 老師管理後台")

    # 密碼驗證
    if not st.session_state.admin_logged_in:
        pwd = st.text_input("Password / 密碼", type="password")
        if st.button("Login / 登入"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.admin_logged_in = True
                st.rerun()
            else:
                st.error("Incorrect password. / 密碼錯誤。")
        st.stop()

    # 登出
    col_title, col_logout = st.columns([5, 1])
    with col_logout:
        if st.button("Logout / 登出"):
            st.session_state.admin_logged_in = False
            st.rerun()

    # 後台分頁
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Dashboard", "✏️ Grading", "👥 Students",
        "📅 Weeks", "📢 Announcements", "⚙️ Settings"
    ])

    settings = storage.get_settings()
    current_semester = settings.get("current_semester", "")

    # ── Tab 1: Dashboard ──────────────────────────────────────
    with tab1:
        import admin_dashboard
        admin_dashboard.render(current_semester)

    # ── Tab 2: Grading ────────────────────────────────────────
    with tab2:
        import admin_grading
        admin_grading.render(current_semester)

    # ── Tab 3: Students ───────────────────────────────────────
    with tab3:
        import admin_students
        admin_students.render(current_semester)

    # ── Tab 4: Weeks ──────────────────────────────────────────
    with tab4:
        import admin_weeks
        admin_weeks.render(current_semester)

    # ── Tab 5: Announcements ──────────────────────────────────
    with tab5:
        import admin_announcements
        admin_announcements.render()

    # ── Tab 6: Settings ───────────────────────────────────────
    with tab6:
        import admin_settings
        admin_settings.render(settings)
