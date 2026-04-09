"""
admin_settings.py — 系統設定分頁
"""
import streamlit as st
import storage


def render(settings: dict):
    st.subheader("System Settings / 系統設定")

    # ── 學期管理 ──────────────────────────────────────────────
    st.markdown("**Semester / 學期管理**")
    current = settings.get("current_semester", "")
    st.caption(f"Current semester / 目前學期：**{current or '（未設定）'}**")

    col1, col2 = st.columns([3, 1])
    with col1:
        new_sem = st.text_input(
            "Set current semester / 設定目前學期",
            value=current,
            placeholder="e.g. 2025-Fall or 2026-Spring"
        )
    with col2:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        if st.button("Save / 儲存", key="save_sem"):
            if new_sem.strip():
                with st.spinner("Saving semester... / 儲存學期中..."):
                    storage.save_setting("current_semester", new_sem.strip())
                    if "settings_cache" in st.session_state:
                        st.session_state.settings_cache["current_semester"] = new_sem.strip()
                st.success("✅ Semester saved! / 學期已儲存！")
                st.rerun()

    # 歷史學期切換（唯讀查看）
    all_settings = storage.get_settings()
    st.divider()
    st.markdown("**View historical semester / 查看歷史學期**")
    st.caption("Changing the current semester above will switch which data is displayed. / 更改上方學期即可切換查看不同學期的資料。")

    st.divider()

    # ── Email 通知設定 ────────────────────────────────────────
    st.markdown("**Email Notifications / Email 通知**")
    st.caption(
        "When set, a daily summary email is sent whenever students submit on that day.  \n"
        "設定後，當天有學生繳交時會寄出每日摘要。留空則不寄。"
    )

    teacher_email = settings.get("teacher_email", "")
    gmail_note = settings.get("gmail_user_set", "")

    new_email = st.text_input(
        "Teacher email / 老師信箱（留空=不寄通知）",
        value=teacher_email,
        placeholder="teacher@example.com"
    )
    if st.button("Save email / 儲存信箱", key="save_email"):
        storage.save_setting("teacher_email", new_email.strip())
        st.success("Saved! / 已儲存！")

    st.caption(
        "Note: Email is sent via Gmail SMTP. Set `GMAIL_USER` and `GMAIL_APP_PASSWORD` in Streamlit Secrets.  \n"
        "注意：需在 Streamlit Secrets 設定 `GMAIL_USER` 和 `GMAIL_APP_PASSWORD`。"
    )

    st.divider()

    # ── App URL（用於 Email 連結）────────────────────────────
    st.markdown("**App URL（for email links / 用於 Email 中的連結）**")
    app_url = settings.get("app_url", "")
    new_url = st.text_input("App URL", value=app_url, placeholder="https://your-app.streamlit.app")
    if st.button("Save URL / 儲存", key="save_url"):
        storage.save_setting("app_url", new_url.strip())
        st.success("Saved!")

    st.divider()

    # ── Secrets 提示 ──────────────────────────────────────────
    st.markdown("**Required Streamlit Secrets / 需要設定的 Secrets**")
    st.code("""
# Streamlit Cloud → Settings → Secrets

ADMIN_PASSWORD = "your_password_here"
GEMINI_API_KEY = "your_gemini_api_key"
GOOGLE_SHEET_ID = "your_google_sheet_id"
GOOGLE_DRIVE_FOLDER_ID = "your_drive_folder_id"
GMAIL_USER = "your_gmail@gmail.com"
GMAIL_APP_PASSWORD = "your_gmail_app_password"
APP_URL = "https://your-app.streamlit.app"

[GOOGLE_CREDENTIALS]
type = "service_account"
project_id = "your-project-id"
private_key_id = "..."
private_key = "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
""", language="toml")
