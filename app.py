"""
app.py — 英文筆記繳交與 AI 輔助評分系統
English Notes Submission & AI Grading System
"""

import streamlit as st
from datetime import datetime
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
if "confirm_overwrite" not in st.session_state:
    st.session_state.confirm_overwrite = False

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
    """共用繳交處理函式"""
    existing = storage.find_record(student_id, week, semester)
    if existing and not st.session_state.confirm_overwrite:
        st.warning(
            f"A submission already exists for **{student_id}** Week {week}.  \n"
            f"**{student_id}** 本週已有繳交紀錄。"
        )
        st.session_state.confirm_overwrite = st.checkbox(
            "Confirm overwrite / 確認覆蓋舊紀錄", key="overwrite_cb"
        )
        return

    st.session_state.confirm_overwrite = False

    with st.spinner("Processing... / 處理中..."):
        pdf_bytes = uploaded_file.read()
        text, read_error = pdf_reader.extract_text_from_bytes(pdf_bytes)
        drive_url = storage.upload_pdf_to_drive(pdf_bytes, f"{student_id}_{student_name}.pdf", semester, week)
        week_config = storage.get_week_config(semester, week)
        key_concepts = week_config.get("key_concepts", "") if week_config else ""

        if read_error or not text.strip():
            score, justification, needs_review = 0, "PDF could not be read (possibly scanned). Manual review required.", True
            scan_flag = True
        else:
            score, justification, needs_review = grader.grade(text, key_concepts)
            scan_flag = False

        record = {
            "semester": semester,
            "student_id": student_id,
            "name": student_name,
            "week": week,
            "filename": f"{student_id}_{student_name}.pdf",
            "drive_url": drive_url or "",
            "ai_score": score,
            "ai_justification": justification,
            "needs_review": needs_review,
            "scan_only": scan_flag,
            "is_late": is_late,
            "final_score": "",
            "released": False,
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        storage.save_record(record, overwrite=bool(existing))

    st.success("Submitted successfully! / 繳交成功！")
    if is_late:
        st.info("This submission is marked as late. / 本次繳交已標記為補交。")
    st.info(
        f"**Student ID / 學號：** {student_id}  \n"
        f"**Name / 姓名：** {student_name}  \n"
        f"**Week / 週次：** Week {week}  \n"
        f"**Submitted at / 繳交時間：** {record['submitted_at']}"
    )
    st.markdown(
        "> Grades will be released after the teacher reviews your submission.  \n"
        "> 成績將在老師審閱後公開，請稍後至查詢成績頁面查看。"
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
    submit_btn = st.button("📤 Submit / 繳交", type="primary", use_container_width=True)

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
            stored_passcode = str(student_info.get("passcode", "")).strip() if student_info else ""

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
                        st.markdown(f"**Submitted at / 繳交時間：** {rec.get('submitted_at', '')}")
                        if released:
                            final = rec.get("final_score") or rec.get("ai_score")
                            st.markdown(f"**Grade / 成績：** {final} / 7")
                            st.markdown(f"**Feedback / 評語：**  \n{rec.get('ai_justification', '')}")
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
