# 部署步驟完整教學

## 概覽：你需要做的事

1. 申請 GitHub 帳號，上傳程式碼
2. 申請 Google API 授權（最繁瑣，約 30 分鐘）
3. 申請 Gemini API Key（5 分鐘）
4. 部署到 Streamlit Cloud（10 分鐘）
5. 設定 Secrets（5 分鐘）
6. 測試

---

## 第一步：GitHub（上傳程式碼）

1. 前往 https://github.com → 點右上角 Sign up → 註冊帳號
2. 登入後點右上角「+」→「New repository」
3. Repository name 填：`notes-grading-system`
4. 選 **Private**（私人，學生看不到）
5. 點「Create repository」
6. 點「uploading an existing file」
7. 把我給你的所有 .py 檔案和 requirements.txt 全部拖拉上去
8. 點「Commit changes」

---

## 第二步：Google Sheets 建立

1. 前往 https://sheets.google.com
2. 新增一個空白試算表
3. 命名為「Notes Grading System」
4. 記下網址中間的 ID，例如：
   `https://docs.google.com/spreadsheets/d/【這一串就是ID】/edit`
5. 把這個 ID 記下來，後面要用

---

## 第三步：Google Drive 建立根資料夾

1. 前往 https://drive.google.com
2. 新增資料夾，命名為「Notes PDF Uploads」
3. 點進資料夾，記下網址最後的 ID，例如：
   `https://drive.google.com/drive/folders/【這一串就是ID】`

---

## 第四步：Google Cloud Console（最複雜的一步）

### 4-1. 建立專案
1. 前往 https://console.cloud.google.com
2. 用你的 Google 帳號登入
3. 點上方「選取專案」→「新增專案」
4. 名稱填「Notes Grading」→「建立」

### 4-2. 啟用 API
1. 左側選單 → API 和服務 → 程式庫
2. 搜尋「Google Sheets API」→ 啟用
3. 搜尋「Google Drive API」→ 啟用

### 4-3. 建立服務帳戶
1. 左側選單 → API 和服務 → 憑證
2. 點「建立憑證」→「服務帳戶」
3. 名稱填「notes-app」→ 建立並繼續 → 完成
4. 點剛建立的服務帳戶 → 點「金鑰」分頁
5. 新增金鑰 → JSON → 建立
6. 瀏覽器會自動下載一個 .json 檔案，**好好保存**

### 4-4. 授權服務帳戶存取你的 Sheets 和 Drive
1. 打開剛下載的 .json 檔案（用記事本）
2. 找到 `"client_email"` 那行，複製那個 email 地址
   （格式像：notes-app@notes-grading.iam.gserviceaccount.com）
3. 回到你的 Google Sheets → 右上角「共用」
4. 貼上那個 email，給「編輯者」權限 → 送出
5. 同樣在 Google Drive 根資料夾 → 共用 → 貼上 email → 編輯者

---

## 第五步：申請 Gemini API Key

1. 前往 https://aistudio.google.com
2. 用 Google 帳號登入
3. 左側「Get API key」→「Create API key」
4. 選你剛建立的 Google Cloud 專案
5. 複製 API Key（一串 AIza 開頭的文字）

---

## 第六步：Gmail App Password（用於 Email 通知）

如果你想要 Email 通知功能：

1. 前往 https://myaccount.google.com/security
2. 確認已開啟「兩步驟驗證」
3. 搜尋「應用程式密碼」→ 建立
4. 選「郵件」→「其他」→ 名稱填「Notes System」→ 產生
5. 複製那 16 位數的密碼

---

## 第七步：部署到 Streamlit Cloud

1. 前往 https://streamlit.io → 點「Sign up」→ 用 GitHub 登入
2. 點「New app」
3. Repository 選 `notes-grading-system`
4. Main file path 填：`app.py`
5. 點「Deploy!」（會跑 1-2 分鐘）

---

## 第八步：設定 Secrets

1. App 部署完成後，點右上角「⋮」→「Settings」
2. 點「Secrets」分頁
3. 貼上以下內容（把各個 ID 和 Key 換成你的）：

```toml
ADMIN_PASSWORD = "你自己設定的後台密碼"
GEMINI_API_KEY = "你的Gemini API Key"
GOOGLE_SHEET_ID = "你的Google Sheets ID"
GOOGLE_DRIVE_FOLDER_ID = "你的Drive資料夾ID"
GMAIL_USER = "你的Gmail帳號@gmail.com"
GMAIL_APP_PASSWORD = "你的Gmail App Password"
APP_URL = "https://你的app名稱.streamlit.app"

[GOOGLE_CREDENTIALS]
type = "service_account"
project_id = "填入json檔的project_id"
private_key_id = "填入json檔的private_key_id"
private_key = "填入json檔的private_key（整段包含BEGIN和END）"
client_email = "填入json檔的client_email"
client_id = "填入json檔的client_id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

4. 點「Save」→ App 自動重啟

---

## 第九步：第一次使用設定

1. 開啟你的 App 網址
2. 點「老師後台」→ 輸入密碼登入
3. 到「Settings」分頁 → 設定目前學期（例如：2025-Fall）
4. 到「Students」分頁 → 上傳學生名單
5. 到「Weeks」分頁 → 開放 Week 01，設定截止日（可不填）
6. 完成！把網址傳給學生

---

## 常見問題

**Q：學生看得到後台嗎？**
A：不會。後台要輸入密碼，學生沒有密碼就進不去。

**Q：PDF 上傳後存在哪裡？**
A：直接存到你的 Google Drive，Streamlit 本身不留任何檔案。

**Q：換學期怎麼做？**
A：老師後台 → Settings → 改目前學期名稱 → 上傳新名單 → 開放新學期的週次。舊學期資料完整保留，隨時可以切回去查。

**Q：App 的網址是什麼格式？**
A：`https://你取的名字.streamlit.app`，部署時可以自訂。

**Q：費用如何？**
A：Streamlit Cloud 免費。Gemini API 35 人一學期約台幣 50-100 元。Google Sheets/Drive 免費。
