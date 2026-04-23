# LINE Bot 雙人記帳系統

基於 LINE Messaging API 的雙人共享記帳系統，支援 AA 平分與自訂分帳。

## 技術棧

- **後端**：Python 3.12 + FastAPI
- **資料庫**：PostgreSQL 16
- **部署**：Docker Compose + Nginx + Let's Encrypt SSL
- **CI/CD**：GitHub Actions → GHCR → SSH 部署

---

## 快速開始（本地開發）

### 1. 複製環境變數

```bash
cp .env.example .env
```

填入：
- `LINE_CHANNEL_SECRET`（從 LINE Developers Console 取得）
- `LINE_CHANNEL_ACCESS_TOKEN`（同上，Issue a channel access token）

### 2. 啟動服務

```bash
docker compose up --build
```

服務將在 http://localhost:8000 啟動。

### 3. 設定 LINE Webhook URL

> ⚠️ LINE 需要公開的 HTTPS URL 才能接收 Webhook。

**🟢 生產環境（推薦）**：部署到伺服器後，直接在 LINE Developers Console 設定：
```
https://alessandra8566.com/webhook
```
前往：LINE Developers Console → Messaging API → Webhook URL → 貼上並驗證。

**🔵 本地開發測試（可選）**：若想在本機測試，用 [ngrok](https://ngrok.com/) 暫時建立公開 tunnel：
```bash
ngrok http 8000
# 將產生的 https://xxxx.ngrok-free.app/webhook 貼到 LINE Console 測試用
# ⚠️ ngrok URL 只是臨時的，測完後要改回正式 domain
```

### 4. 執行測試

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## 對話流程

```
使用者：晚餐 320
Bot：📝 晚餐 NT$ 320 — 這筆錢是誰付的？ [我付的] [對方付的]

→ 點 我付的：
Bot：請選擇分帳方式 [AA平分] [自訂分帳]

    → 點 AA：
    Bot：✅ 已記帳：晚餐 | 總額 320 | 你 160 | 對方 160

    → 點自訂：
    Bot：請輸入你要負擔的金額...
    使用者：我 200
    Bot：✅ 已記帳：晚餐 | 總額 320 | 你 200 | 對方 120
```

### 配對流程

```
使用者 A：配對
Bot：🔗 你的邀請碼：ABC123（24小時有效）

使用者 B：配對 ABC123
Bot：✅ 已成功與 使用者A 配對！
```

## LINE Bot 功能清單

本系統提供以下核心功能，您可以透過文字指令或按鈕選單進行操作：

### 1️⃣ 日常記帳 (核心功能)
*   **快速輸入**：直接傳送「品項 金額」（例如：`早餐 80`）即可開始。
*   **付款人選擇**：支援選擇「我付的」或「對方付的」，方便代為記帳。
*   **分帳模式**：
    *   **AA 平分**：系統自動將金額除以 2。
    *   **自訂分帳**：手動輸入自己負擔的金額（例如：`我 50`），系統自動計算餘額。

### 2️⃣ 帳務查詢與結算
*   **查詢結算**：即時顯示目前雙方的差額（誰欠誰多少錢）。
*   **歷史紀錄**：查看最近 10 筆尚未結清的消費細節。

### 3️⃣ 系統管理
*   **雙人配對**：透過邀請碼機制將兩位使用者連結。
*   **清帳功能**：當雙方完成現實中的還款後，可將所有舊帳目一鍵歸零。
*   **功能選單**：輸入「選單」或「Help」可呼叫出功能按鈕，無需背誦指令。

### 指令對照表

| 指令/輸入 | 功能說明 |
| :--- | :--- |
| `品項 金額` | 啟動記帳流程 (例如：`晚餐 350`) |
| `選單` / `Menu` | 呼叫主功能按鈕選單 |
| `配對` | 產生一組 24 小時有效的邀請碼 |
| `配對 XXXXXX` | 輸入對方的邀請碼進行綁定 |
| `我 金額` | 在自訂分帳模式下使用 (例如：`我 200`) |

---

## 生產部署

### 伺服器初始設定（只需一次）

SSH 進入伺服器 `188.166.226.40`：

```bash
# 1. 安裝 Docker
curl -fsSL https://get.docker.com | sh

# 2. 建立專案目錄
mkdir ~/expense-tracker && cd ~/expense-tracker

# 3. 複製 nginx 設定
mkdir -p nginx
# 上傳 nginx/nginx.conf 和 docker-compose.prod.yml

# 4. 申請 SSL 憑證
docker run --rm -p 80:80 certbot/certbot certonly \
  --standalone \
  -d alessandra8566.com \
  -d www.alessandra8566.com \
  --email your@email.com --agree-tos --no-eff-email
```

### GitHub Secrets 設定

前往 GitHub Repo → Settings → Secrets and variables → Actions，新增：

| Secret | 值 |
|--------|---|
| `SSH_HOST` | `188.166.226.40` |
| `SSH_USER` | 伺服器用戶名（通常是 `root` 或 `ubuntu`） |
| `SSH_PRIVATE_KEY` | SSH 私鑰內容 |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | 自訂強密碼 |

### 部署

推送至 `main` branch 即自動觸發 CI/CD：

```bash
git push origin main
```

流程：測試 → 建置 Docker image → 推送 GHCR → SSH 部署

---

## 專案結構

```
expense-tracker/
├── app/
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 環境變數
│   ├── database.py           # SQLAlchemy async engine
│   ├── models/               # DB 模型
│   │   ├── user.py
│   │   ├── expense.py
│   │   └── user_state.py
│   ├── routers/
│   │   └── webhook.py        # LINE Webhook 路由 + State Machine
│   └── services/
│       ├── line_service.py   # LINE SDK 封裝
│       ├── state_machine.py  # 狀態管理
│       ├── expense_service.py # 記帳業務邏輯
│       └── settlement.py     # 結算計算
├── tests/
├── nginx/nginx.conf
├── .github/workflows/deploy.yml
├── docker-compose.yml        # 開發用
├── docker-compose.prod.yml   # 生產用
└── Dockerfile
```
