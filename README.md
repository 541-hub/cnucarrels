# 嘉南藥理大學 圖書館研究小間 自動預約機器人

自動登入 https://carrel.cnu.edu.tw 並嘗試預約研究小間 / 討論室。
支援兩種排程方式：**GitHub Actions 雲端排程**（推薦，電腦不用開機）或**本機 cron**。

## 專案結構

```
.
├── cnu_carrel_bot.py           # 主程式，不用改
├── requirements.txt
├── .env.example                # 本機測試用的範本（假資料，複製成 .env 使用）
├── .gitignore
├── .github/workflows/book-room.yml   # GitHub Actions 排程設定
└── README.md
```

## 已完成

登入表單選擇器、驗證碼讀取（不需要 OCR，直接讀 HTML 文字節點）、預約研究小間的完整流程都已經寫好。
程式會：
1. 登入（帳號、末四碼、驗證碼都自動填寫）
2. 點擊「按日借用研究小間」
3. 用頁面預設的日期（執行當天）查詢可預約空間
4. 找到指定房號，點擊該房間的「預約」按鈕

## 方式一：本機測試（無論之後選哪種排程，都建議先做這步）

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

打開 `.env`，填入你的學號、身分證末四碼、想預約的房號。**這個檔案只會留在你自己電腦，`.gitignore` 已經排除它，不會被上傳。**

```bash
python3 cnu_carrel_bot.py
```

看 log（同時印在畫面上、存到 `cnu_carrel_bot.log`），確認登入、查詢、預約每一步是否成功。

## 方式二：GitHub Actions 雲端自動化（推薦）

好處：不需要自己的電腦在排程時間保持開機、不斷網、不睡眠，由 GitHub 的雲端機器代為執行，個人帳號免費額度對這種「每天跑幾分鐘」的任務綽綽有餘。

### 設定步驟

1. 在 GitHub 建立一個新的 **Private** repository（務必設為 Private）
2. 把這個資料夾的內容 push 上去。**上傳前務必再檢查一次沒有把 `.env` 或任何寫著真實學號/末四碼的檔案加進去**——`git status` 應該看不到 `.env`
3. 到 repo 的 `Settings → Secrets and variables → Actions → Secrets` 頁面，新增三組 Repository secret：
   - `CNU_STUDENT_ID`：你的學號
   - `CNU_ID_LAST4`：身分證末四碼
   - `CNU_ROOM_NUMBER`：想預約的房號（例如 `401`）
   這三個值會被加密存放，Actions 的執行紀錄也不會顯示明碼
4. 到 repo 的 `Actions` 分頁，點選「自動預約研究小間」這個 workflow，按右上角 `Run workflow` 手動觸發一次
5. 執行完成後點進該次 run，下載 `carrel-bot-log-*` 這個 artifact，打開確認裡面顯示「登入成功」「已送出房號 XXX 的預約」
6. 確認沒問題後，之後就交給排程了——目前設定的是每天 UTC 00:59（= 台灣時間 08:59）自動執行一次

### 想改執行時間？

`book-room.yml` 裡 `cron` 那行的時間是 **UTC**，不是台灣時間，換算方式是「**台灣時間 − 8 小時 = UTC 時間**」。
例如想改成台灣時間 07:30 執行，UTC 就是前一天 23:30，寫成 `30 23 * * *`。

### 雲端排程的限制（要知道的事）

- GitHub 的排程觸發是「盡力而為」，尖峰時段可能延遲個幾分鐘。如果房間是整點開放、需要搶快，本機 cron 在自己電腦上執行可能反而更準時
- 如果這個 repo 超過 60 天沒有任何 commit，GitHub 會自動停用排程觸發（手動按 `Run workflow` 不受影響），要記得偶爾檢查一下有沒有正常執行
- 建議偶爾去 `Actions` 分頁看一下有沒有跑失敗，網站改版時（換驗證碼樣式、欄位名稱）程式可能需要跟著調整

## 方式三：本機 cron（原本的做法，仍可用）

適合想要「時間點更準」或不想把學號等資料放到任何雲端服務（即使是加密的 Secrets）的人。

1. 確認虛擬環境裡 `python3` 的完整路徑：`which python3`
2. 執行 `crontab -e`，加入一行（路徑換成你自己的）：
   ```
   59 8 * * * cd "/你的專案路徑" && "/你的專案路徑/venv/bin/python3" cnu_carrel_bot.py >> cron.log 2>&1
   ```
3. `crontab -l` 確認排程已加入；到時間後看 `cron.log` 和 `cnu_carrel_bot.log` 確認結果

macOS 較新版本對 cron 存取檔案有隱私權限限制：`系統設定 → 隱私權與安全性 → 完整磁碟取用權限`，把 `/usr/sbin/cron` 加進去並打開權限。

## 注意事項

- 學校系統的預約規則、每日開放時間、單人可預約時數上限等，請自行確認校方規定，自動化只是幫你「準時送出申請」，不要用它規避使用規則（例如同時預約超過上限、一次佔用多間），以免帳號被停權
- `CNU_ID_LAST4`（身分證末四碼）在這個系統裡等同密碼，不管本機或雲端都要當密碼一樣謹慎處理，不要貼到公開的地方
- 若學校網站之後改版（換了驗證碼樣式、欄位名稱），程式可能需要跟著調整
