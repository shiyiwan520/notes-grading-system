"""
admin_students.py — 學生名單管理（含驗證碼設定）
"""
import streamlit as st
import pandas as pd
import storage


def render(semester: str):
    st.subheader("Student List / 學生名單")

    if not semester:
        st.info("Please set the current semester in Settings first. / 請先在 Settings 設定目前學期。")
        return

    students = storage.get_students(semester)

    if students:
        df = pd.DataFrame(students)
        show_cols = ["student_id", "name", "passcode"]
        for c in show_cols:
            if c not in df.columns:
                df[c] = ""
        df = df[show_cols]
        df["passcode"] = df["passcode"].apply(lambda x: "🔒 Set" if str(x).strip() else "—")
        df.columns = ["Student ID / 學號", "Name / 姓名", "Passcode / 驗證碼"]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(students)} students / 共 {len(students)} 名學生")
    else:
        st.info("No students in this semester yet. / 本學期尚無學生名單。")

    st.divider()

    # ── 方法1：貼上 CSV 文字 ──────────────────────────────────
    st.markdown("**Method 1: Paste CSV / 方式一：貼上 CSV 格式文字**")
    st.caption(
        "Format: student_id,name (no header) / 格式：學號,姓名（每行一筆，不需要表頭）  \n"
        "Passcode can be added later below. / 驗證碼可以事後在下方單獨設定。"
    )
    csv_text = st.text_area(
        "Paste here / 貼上文字",
        placeholder="M1344001,王小明\nM1344002,陳美麗\nM1344003,John Smith",
        height=150,
        key="csv_paste"
    )
    if st.button("Import from text / 從文字匯入", key="import_text"):
        if not csv_text.strip():
            st.error("Please paste some content first. / 請先貼上內容。")
        else:
            with st.spinner("Importing... / 匯入中..."):
                parsed = _parse_csv_text(csv_text)
            if parsed:
                with st.spinner(f"Saving {len(parsed)} students... / 儲存 {len(parsed)} 名學生到雲端..."):
                    try:
                        storage.save_students(semester, parsed)
                        st.success(f"✅ Imported {len(parsed)} students! / 成功匯入 {len(parsed)} 名學生！")
                        st.rerun()
                    except Exception as save_err:
                        st.error(f"Save failed / 儲存失敗：{save_err}")
            else:
                st.error("Could not parse. Check format (no header). / 無法解析，請確認格式且無表頭。")

    st.divider()

    # ── 方法2：上傳 CSV 檔案 ──────────────────────────────────
    st.markdown("**Method 2: Upload CSV file / 方式二：上傳 CSV 檔案**")
    uploaded = st.file_uploader("Upload CSV / 上傳 CSV", type=["csv"], key="csv_upload")
    if uploaded:
        if st.button("Import from file / 從檔案匯入", key="import_file"):
            try:
                with st.spinner("Reading file... / 讀取檔案中..."):
                    raw = uploaded.read()
                    # 嘗試多種編碼
                    for enc in ["utf-8-sig", "utf-8", "big5", "cp950"]:
                        try:
                            text = raw.decode(enc)
                            break
                        except Exception:
                            text = None
                    if not text:
                        st.error("Cannot decode file. Please save CSV as UTF-8. / 無法解碼檔案，請將 CSV 儲存為 UTF-8 格式。")
                        st.stop()

                    # 移除 BOM
                    text = text.lstrip("\ufeff").strip()
                    parsed = []
                    errors = []
                    for i, line in enumerate(text.splitlines(), start=1):
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split(",", 1)
                        if len(parts) != 2:
                            errors.append(f"Row {i}: cannot parse '{line}'")
                            continue
                        sid = parts[0].strip().upper()
                        name = parts[1].strip()
                        if sid.lower() in ("student_id", "學號", "id"):
                            continue
                        if sid and name:
                            parsed.append({"student_id": sid, "name": name, "passcode": ""})

                if errors:
                    st.warning(f"Skipped {len(errors)} invalid row(s): {'; '.join(errors[:3])}")

                if parsed:
                    with st.spinner(f"Saving {len(parsed)} students... / 儲存 {len(parsed)} 名學生到雲端..."):
                        storage.save_students(semester, parsed)
                    st.success(f"✅ Imported {len(parsed)} students! / 成功匯入 {len(parsed)} 名學生！")
                    st.rerun()
                else:
                    st.error(
                        "No valid rows found. Make sure format is: student_id,name (no header, comma separated).\n"
                        "找不到有效資料。請確認格式為：學號,姓名（無表頭，逗號分隔）。"
                    )
            except Exception as e:
                st.error(f"Import failed / 匯入失敗：{e}")

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
                with st.spinner("Saving... / 儲存中..."):
                    try:
                        existing = storage.get_students(semester)
                        if any(s["student_id"].upper() == new_id for s in existing):
                            st.warning("⚠️ Student ID already exists. / 學號已存在。")
                        else:
                            existing.append({"student_id": new_id, "name": new_name, "passcode": ""})
                            storage.save_students(semester, existing)
                            st.success(f"✅ Added {new_id} {new_name}!")
                            st.rerun()
                    except Exception as save_err:
                        st.error(f"Save failed / 儲存失敗：{save_err}")
            else:
                st.error("Please fill in both fields. / 請填寫學號與姓名。")

    st.divider()

    # ── 驗證碼管理 ────────────────────────────────────────────
    st.markdown("**Passcode Management / 驗證碼管理**")
    st.caption(
        "Students who want grade privacy can provide a passcode to the teacher.  \n"
        "想保護成績隱私的學生可私下告知老師驗證碼，設定後查詢成績時需輸入才能看到。  \n"
        "Leave blank to remove passcode. / 留空可取消驗證碼。"
    )

    if students:
        student_options = [f"{s['student_id']} — {s['name']}" for s in students]
        selected = st.selectbox("Select student / 選擇學生", student_options, key="passcode_student")
        selected_id = selected.split(" — ")[0]
        current_pc = next(
            (str(s.get("passcode","")).strip() for s in students
             if s["student_id"].upper() == selected_id), ""
        )
        st.caption(f"Current passcode / 目前驗證碼：{'🔒 Set / 已設定' if current_pc else '— Not set / 未設定'}")
        new_pc = st.text_input(
            "New passcode / 新驗證碼（留空=取消驗證碼）",
            placeholder="e.g. 0815 (last 4 digits of birthday)",
            key="new_passcode"
        ).strip()
        if st.button("Save passcode / 儲存驗證碼", key="save_pc"):
            with st.spinner("Saving... / 儲存中..."):
                ok = storage.update_student_passcode(semester, selected_id, new_pc)
            if ok:
                if new_pc:
                    st.success(f"✅ Passcode set for {selected_id}. / 已設定驗證碼！")
                else:
                    st.success(f"✅ Passcode removed for {selected_id}. / 已取消驗證碼！")
                st.rerun()
            else:
                st.error("Failed to save. / 儲存失敗。")

    st.divider()

    # ── CSV 範本下載 ──────────────────────────────────────────
    template = "M1344001,王小明\nM1344002,陳美麗\nM1344003,John Smith\n"
    st.download_button(
        "📥 Download CSV template / 下載 CSV 範本",
        data=template.encode("utf-8-sig"),
        file_name="students_template.csv",
        mime="text/csv"
    )


def _parse_csv_text(text: str):
    result = []
    # 移除 BOM 字元
    text = text.lstrip('﻿')
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 1)
        if len(parts) == 2:
            sid = parts[0].strip().upper()
            name = parts[1].strip()
            if sid.lower() in ("student_id", "學號", "id") or name.lower() in ("name", "姓名"):
                continue
            if sid and name:
                result.append({"student_id": sid, "name": name, "passcode": ""})
    return result
