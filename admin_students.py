"""
admin_students.py — 學生名單管理分頁
"""
import streamlit as st
import pandas as pd
import io
import storage


def render(semester: str):
    st.subheader("Student List / 學生名單")

    if not semester:
        st.info("Please set the current semester in Settings first.")
        return

    students = storage.get_students(semester)

    # 現有名單
    if students:
        df = pd.DataFrame(students)[["student_id", "name"]]
        df.columns = ["Student ID / 學號", "Name / 姓名"]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(students)} students / 共 {len(students)} 名學生")
    else:
        st.info("No students in this semester yet. / 本學期尚無學生名單。")

    st.divider()

    # ── 方法1：貼上 CSV 文字 ──────────────────────────────────
    st.markdown("**Method 1: Paste CSV / 方式一：貼上 CSV 格式文字**")
    st.caption("Format: student_id,name (one per line) / 格式：學號,姓名（每行一筆）")
    csv_text = st.text_area(
        "Paste here / 貼上文字",
        placeholder="M1344001,王小明\nM1344002,陳美麗\nM1344003,John Smith",
        height=150,
        key="csv_paste"
    )
    if st.button("Import from text / 從文字匯入", key="import_text"):
        parsed = _parse_csv_text(csv_text)
        if parsed:
            storage.save_students(semester, parsed)
            st.success(f"Imported {len(parsed)} students. / 已匯入 {len(parsed)} 名學生。")
            st.rerun()
        else:
            st.error("Could not parse CSV. Check format. / 無法解析，請確認格式。")

    st.divider()

    # ── 方法2：上傳 CSV 檔案 ──────────────────────────────────
    st.markdown("**Method 2: Upload CSV file / 方式二：上傳 CSV 檔案**")
    uploaded = st.file_uploader("Upload CSV / 上傳 CSV", type=["csv"], key="csv_upload")
    if uploaded and st.button("Import from file / 從檔案匯入", key="import_file"):
        try:
            df_upload = pd.read_csv(uploaded, header=None, names=["student_id", "name"])
            parsed = df_upload.dropna().to_dict("records")
            parsed = [{"student_id": str(r["student_id"]).strip().upper(),
                       "name": str(r["name"]).strip()} for r in parsed if r["student_id"] and r["name"]]
            if parsed:
                storage.save_students(semester, parsed)
                st.success(f"Imported {len(parsed)} students.")
                st.rerun()
            else:
                st.error("No valid rows found.")
        except Exception as e:
            st.error(f"Error: {e}")

    st.divider()

    # ── 方法3：手動新增單筆 ───────────────────────────────────
    st.markdown("**Method 3: Add one student / 方式三：手動新增單筆**")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        new_id = st.text_input("Student ID / 學號", key="new_id").strip().upper()
    with col2:
        new_name = st.text_input("Name / 姓名", key="new_name").strip()
    with col3:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        if st.button("Add / 新增", key="add_one"):
            if new_id and new_name:
                existing = storage.get_students(semester)
                if any(s["student_id"].upper() == new_id for s in existing):
                    st.warning("Student ID already exists. / 學號已存在。")
                else:
                    existing.append({"student_id": new_id, "name": new_name})
                    storage.save_students(semester, existing)
                    st.success("Added! / 已新增！")
                    st.rerun()
            else:
                st.error("Please fill in both fields. / 請填寫學號與姓名。")

    # ── CSV 範本下載 ──────────────────────────────────────────
    st.divider()
    template = "student_id,name\nM1344001,王小明\nM1344002,John Smith\n"
    st.download_button(
        "📥 Download CSV template / 下載 CSV 範本",
        data=template.encode("utf-8-sig"),
        file_name="students_template.csv",
        mime="text/csv"
    )


def _parse_csv_text(text: str):
    result = []
    for line in text.strip().splitlines():
        parts = line.strip().split(",", 1)
        if len(parts) == 2:
            sid = parts[0].strip().upper()
            name = parts[1].strip()
            if sid and name:
                result.append({"student_id": sid, "name": name})
    return result
