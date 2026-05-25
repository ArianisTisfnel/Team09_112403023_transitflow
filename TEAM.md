# TransitFlow 組員協作手冊

> 本文件是全體組員的**操作共識**。每次開始工作前請確認本文件內容，
> 並在做出影響全員的決定時更新對應區塊。
>
> 相關文件：[TEAM_AI_WORKFLOW.md](TEAM_AI_WORKFLOW.md)（AI 輔助開發指南）｜[AI_SESSION_CONTEXT.md](AI_SESSION_CONTEXT.md)（AI Session 共享上下文）

---

## 目錄

- [1. 成員分工表](#1-成員分工表)
- [2. 實作計畫與里程碑](#2-實作計畫與里程碑)
- [3. 專案目錄結構說明](#3-專案目錄結構說明)
- [4. Git 操作規範](#4-git-操作規範)
- [5. 程式碼審查規範](#5-程式碼審查規範)
- [6. 開發環境快速設定](#6-開發環境快速設定)

---

## 1. 成員分工表

| 姓名 | 主要負責範圍 | 對應文件 | 狀態 |
|------|------------|---------|------|
| 康睿恩 | 開發流程規劃、實作計畫撰寫、Stage 3 基礎設施實作、單元測試與整合測試、測試報告撰寫、專案協作程式碼審查 | docs/23–26、tests/、reports/testing/ | 🟡 進行中 |
| 陳玟茹 | **主軸 A**：關聯式資料庫 schema 設計、PostgreSQL 查詢函式實作、進階功能（選做） | docs/04–12、docs/21–22 | 🔲 待認領 |
| 組員 C（待認領） | **主軸 B**：Neo4j 圖形 schema 設計、種子資料腳本、圖形查詢函式實作 | docs/13–20 | 🔲 待認領 |

> **認領方式**：在本表格填上自己的名字，commit 訊息寫 `docs(team): 認領主軸 X 分工`，push 並告知全員。

---

### 1.1 詳細任務清單

#### 康睿恩（已完成 / 進行中）

- [x] 開發流程規劃（`TEAM_AI_WORKFLOW.md`）
- [x] 完整實作計畫撰寫（`docs/00–26`）
- [x] `AI_SESSION_CONTEXT.md` 建立與維護
- [x] 函式簽名對齊驗證（docs 08/09/20/24/25）
- [ ] **Stage 3.1**：`skeleton/exceptions.py`（`TransitFlowException` + `@error_handler`）
- [ ] **Stage 3.2**：`skeleton/database_service.py`（ABC + DI 重構 `skeleton/agent.py`）
- [ ] **Stage 3.3**：`skeleton/cache.py`（CacheManager）+ `databases/graph/connection_pool.py`
- [ ] **Stage 3.4**：`skeleton/structured_logger.py` + Prometheus 指標 + `healthz()` + `chat()` 生成器
- [ ] 單元測試（`tests/unit/`）
- [ ] 整合測試（`tests/integration/`）
- [ ] 測試報告（`reports/testing/`）
- [ ] 各階段實作報告審閱（`reports/implementation/`）
- [ ] 所有 PR 程式碼審查

#### 組員 B（主軸 A — 關聯式資料庫）

- [ ] **Schema 設計**：`databases/relational/schema.sql`（參考 docs/04–05）
  - 核心表格：`users`、`metro_stations`、`national_rail_stations`、`metro_station_adjacencies`
  - 交通表格：`metro_schedules`、`national_rail_schedules`、`national_rail_seat_layouts`、`national_rail_bookings`、`metro_travel_history`、`payments`、pgvector index
- [ ] **查詢函式**：`databases/relational/queries.py`
  - `query_user_profile` / `query_user_bookings` / `query_payment_info`（docs/06）
  - `query_national_rail_availability`（docs/07）
  - `query_national_rail_fare` / `query_metro_schedules`（docs/08）
  - `query_metro_fare` / `query_available_seats` / `auto_select_adjacent_seats`（docs/09）
  - `execute_booking`（docs/10）
  - `execute_cancellation`（docs/11）
  - `register_user` / `login_user` / `get_user_secret_question` / `verify_secret_answer` / `update_password`（docs/12）
- [ ] （選做）進階功能：`query_alternative_schedules_fallback`、`query_schedules_by_date_range`（docs/21）
- [ ] （選做）分析查詢：`query_round_trip_itinerary`、`query_daily_revenue_report` 等（docs/22）
- [ ] 撰寫實作報告（`reports/implementation/stage1-a-relational-queries.md`）

#### 組員 C（主軸 B — 圖形資料庫）

- [ ] **Graph schema 設計**（與組員 B 協作確認 station_id 命名）
- [ ] **Neo4j 種子腳本**：`skeleton/seed_neo4j.py`
  - `:Station` 節點種子（docs/13）
  - `CONNECTS_TO` 關係種子（docs/14）
  - `INTERCHANGE` 關係種子，雙向（docs/15）
- [ ] **scaffold 清理**（開始實作前立即執行）：
  - 刪除 `databases/graph/queries.py` 頂部的 `from neo4j import GraphDatabase` 與 `def _driver():`
  - 在 `databases/graph/` 建立最小化 `connection_pool.py` stub
- [ ] **圖形查詢函式**：`databases/graph/queries.py`
  - `query_shortest_route` / `query_station_connections`（docs/16）
  - `query_alternative_routes`（docs/17）
  - `query_interchange_path` / `validate_interchange_feasibility`（docs/18）
  - `query_delay_ripple`（docs/19）
  - `query_cheapest_route`（docs/20，依賴主軸 A 的票價函式）
- [ ] 撰寫實作報告（`reports/implementation/stage1-b-graph-queries.md`）

---

## 2. 實作計畫與里程碑

### 整體閱讀順序

```
docs/01（需求）→ docs/03（整體藍圖）→ 認領主軸 A 或 B → Stage 3（基礎設施）
```

### 里程碑規劃

```
M0  Schema Design  ─────────────────────────────────────────────────────────
    ☑  Schema 設計工作坊（三人同步完成，約 90 分鐘）
    ☑  AI_SESSION_CONTEXT.md 填入確定的 schema
    ☑  schema.sql 合併至 main（需全員 approve PR）

M1  Stage 1/2 平行開發  ──────────────────────────────────────────────────
    ├─ 主軸 A：docs/04–12（PostgreSQL）
    │    04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12
    └─ 主軸 B：docs/13–20（Neo4j）
         13 → 14 → 15 → 16 → 17 → 18 → 19 → 20
         ↳ 20 跨模組依賴主軸 A 的 query_national_rail_fare + query_metro_fare

M2  進階功能（選做）  ────────────────────────────────────────────────────
    docs/21（fallback date-range）、docs/22（round-trip analytics）

M3  Stage 3 基礎設施  ───────────────────────────────────────────────────
    23（exceptions）→ 24（DI + ABC）→ 25（cache + connection pool）→ 26（UI + observability）

M4  測試與驗收  ──────────────────────────────────────────────────────────
    ☑  pytest tests/unit/ -v  （全部 PASS）
    ☑  pytest tests/integration/ -v  （全部 PASS）
    ☑  撰寫並提交測試報告（reports/testing/final-validation-report.md）
```

### 依賴關係一覽

```
主軸 A：04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12
                                              ↑
進階：  21（依賴 07、08）
        22（依賴 07、09、10）

主軸 B：13 → 14 → 15 → 16 → 17 → 18 → 19 → 20
                                           ↑
                    20 跨模組呼叫主軸 A：query_national_rail_fare + query_metro_fare

Stage 3：23 → 24 → 25 → 26
          ↑
          25 的 CacheManager 整合回主軸 A 的 queries.py（query_national_rail_fare / query_metro_schedules）
          25 的 connection_pool 整合回主軸 B 的 queries.py
```

---

## 3. 專案目錄結構說明

```
transitflow/
├── AI_SESSION_CONTEXT.md    ← AI 共享上下文（每次 session 開始時貼入 AI）
├── TEAM.md                  ← 本文件：分工、計畫、Git 規範
├── TEAM_AI_WORKFLOW.md      ← AI 輔助開發流程指南
│
├── databases/
│   ├── relational/
│   │   ├── schema.sql       ← 關聯式 schema（全員同意後合併）
│   │   └── queries.py       ← 主軸 A 實作目標（scaffold 已存在，新增函式即可）
│   └── graph/
│       ├── queries.py       ← 主軸 B 實作目標（需先清理 scaffold）
│       └── connection_pool.py  ← Stage 3.3 建立（Stage 1/2 用 stub）
│
├── skeleton/                ← Stage 3 實作目標
│   ├── agent.py             ← Stage 3.2 DI 重構
│   ├── cache.py             ← Stage 3.3 建立
│   ├── database_service.py  ← Stage 3.2 建立
│   ├── exceptions.py        ← Stage 3.1 建立
│   ├── structured_logger.py ← Stage 3.4 建立
│   ├── metrics.py           ← Stage 3.4 建立
│   ├── vector_warmup.py     ← Stage 3.3 建立
│   ├── config.py            ← ⛔ 禁止修改
│   ├── llm_provider.py      ← ⛔ 禁止修改
│   └── seed_vectors.py      ← ⛔ 禁止修改
│
├── tests/                   ← 測試目錄
│   ├── unit/                ← 單元測試（不需 DB 連線）
│   └── integration/         ← 整合測試（需 Docker 環境）
│
├── reports/
│   ├── implementation/      ← 各階段實作報告（README.md 內有說明）
│   └── testing/             ← 測試執行報告（README.md 內有說明）
│
├── docs/                    ← 完整實作指南（00–26，不要修改）
└── train-mock-data/         ← 原始 JSON mock 資料
```

---

## 4. Git 操作規範

### 4.1 分支策略

本專案採用 **Feature Branch Workflow**：
- `main` — 保護分支，只接受 Pull Request，不直接 push
- `feature/<姓名>/<功能描述>` — 功能開發分支
- `fix/<姓名>/<修復描述>` — Bug 修復分支
- `docs/<姓名>/<描述>` — 文件更新分支
- `test/<姓名>/<描述>` — 測試撰寫分支

### 4.2 分支命名規範

**格式**：`<類型>/<姓名>/<簡短描述>`，以小寫英文和連字符組成

```bash
# ✅ 正確範例
feature/alice/relational-schema
feature/bob/graph-shortest-route
feature/carol/neo4j-seed-stations
fix/alice/metro-fare-null-schedule
test/carol/unit-query-metro-schedules
docs/alice/update-ai-context

# ❌ 錯誤範例
feature/Alice/Relational Schema    # 含大寫和空格
my-branch                          # 無類型前綴
feature/implement-everything       # 範圍過大
```

### 4.3 Commit 訊息格式（Conventional Commits）

**格式**：`<類型>(<範圍>): <動詞開頭的描述>`

| 類型 | 用途 |
|------|------|
| `feat` | 新增功能（新函式、新模組） |
| `fix` | 修復 bug |
| `test` | 新增或修改測試 |
| `docs` | 文件變更（包含 `.md` 檔案） |
| `refactor` | 重構（行為不變，結構改變） |
| `chore` | 雜務（依賴更新、設定檔、目錄建立） |
| `style` | 格式整理（不影響行為） |

**範圍**（選填）：`relational`、`graph`、`skeleton`、`tests`、`docs`、`schema`

```bash
# ✅ 正確範例
feat(relational): implement query_metro_schedules
feat(relational): implement query_national_rail_fare with schedule_id lookup
feat(graph): implement query_shortest_route using APOC Dijkstra
fix(relational): correct TO_CHAR format in query_metro_schedules
test(unit): add tests for query_national_rail_fare multipliers
docs(team): update AI_SESSION_CONTEXT.md with agreed schema
chore: add reports and tests directory structure
refactor(skeleton): apply DI pattern to TransitFlowAgent

# ❌ 錯誤範例
update stuff            # 不清楚
fix bug                 # 無描述
WIP                     # 不可提交半成品到 main
added query function    # 動詞時態不一致
```

### 4.4 原子提交原則（Atomic Commits）

每個 commit 應該只包含**一個邏輯變更**，使其可以獨立被 revert 或 cherry-pick。

**判斷標準**：如果一個 commit 的描述需要用「AND」連接，就應該拆成兩個 commit。

```bash
# ✅ 正確：一個 commit 一件事
git commit -m "feat(relational): implement query_metro_schedules"
git commit -m "test(unit): add query_metro_schedules unit tests"

# ❌ 錯誤：一個 commit 做太多事
git commit -m "implement query_metro_schedules and fix query_metro_fare and update schema"
```

**不要把以下這些混在同一個 commit**：
- Schema 變更 + 查詢函式實作
- 多個不相關的函式實作
- 功能實作 + 測試 + 文件更新（若三者很大量）

**例外情況**：  
若測試與實作非常緊密且都很小，可以一起提交：
```bash
git commit -m "feat(relational): implement query_user_profile with unit test"
```

### 4.5 每次工作 Session 標準流程

```bash
# ① 同步最新代碼（每次開始前必做）
git checkout main
git pull origin main

# ② 開新分支
git checkout -b feature/alice/query-metro-schedules

# ③ 工作中頻繁提交（小步提交）
git add databases/relational/queries.py # 將本地的變更檔案添加至暫存
git commit -m "feat(relational): implement query_metro_schedules" # 將所有添加檔案提交到本地分支，並提供提交訊息

# ④ 完成後推送
git push origin feature/alice/query-metro-schedules

# ⑤ 在 GitHub 開 Pull Request，指定審查者
# ⑥ 處理 review 意見，推送修正

# ⑦ 合併後清理（本地刪除分支）
git checkout main
git pull origin main
git branch -d feature/alice/query-metro-schedules
```

### 4.6 Pull Request 規則

**PR 開啟條件**：
- 功能完整（不提交明顯有誤的半成品）
- 本地測試通過（至少確認對應函式的測試命令不報錯）
- 無 merge conflict（開 PR 前先 rebase/merge main）

**PR 描述模板**：
```markdown
## 變更摘要
本 PR 實作 `query_metro_schedules`，依 origin_id / destination_id 查詢捷運班次。

## 對應文件
- [docs/08-A-query-nr-fare-metro-schedules.md](docs/08-A-query-nr-fare-metro-schedules.md)

## 測試
```bash
pytest tests/unit/ -v -k "metro_schedules"
```
結果：X passed, X warnings

## 注意事項（給 reviewer）
- 使用 TO_CHAR 格式化時間欄位，請確認與測試期望格式一致
```

**合併規則**：
- **至少 1 位組員 Approve** 才可合併
- 建議康睿恩負責主要審查（code review 負責人）
- 使用 **Squash and Merge** 保持 main 分支的 commit 歷史整潔

### 4.7 合併衝突處理

若 PR 遭遇 merge conflict：

```bash
# 方法一：rebase（推薦，保持線性歷史）
git checkout feature/alice/query-metro-schedules
git fetch origin
git rebase origin/main
# 解決衝突後
git add <衝突檔案>
git rebase --continue
git push --force-with-lease origin feature/alice/query-metro-schedules

# 方法二：merge（較安全，但會產生 merge commit）
git checkout feature/alice/query-metro-schedules
git merge origin/main
# 解決衝突，然後 commit 並 push
```

**衝突最常見的原因**：
- 多人同時修改 `databases/relational/queries.py` — 建議功能不重疊時分開提交
- `AI_SESSION_CONTEXT.md` 被多人同時更新 — 以最新版為準，手動合併

### 4.8 重要：Schema 鎖定規則

Schema 合併至 main 後，**任何表格名稱或欄位名稱的變更**都必須：
1. 在群組討論後達成共識
2. 更新 `AI_SESSION_CONTEXT.md` 的 schema 區塊
3. 更新所有引用該欄位的查詢函式
4. PR 需全員 Approve 才可合併

---

## 5. 程式碼審查規範

### 5.1 審查者職責

每個 PR 的審查者應逐項確認以下 Checklist：

#### 關聯式查詢函式 Checklist

```
[ ] 函式簽名是否與 AI_SESSION_CONTEXT.md 的 Fixed Contracts 完全一致？
[ ] 使用了 _connect() helper + psycopg2.extras.RealDictCursor 模式？
[ ] 所有 SQL 輸入使用 %s placeholder，沒有字串格式化？
[ ] 找不到結果時回傳 [] 或 None（不 raise exception）？
[ ] 回傳 dict 的 key 名稱與 docs 規格一致？
[ ] Stage 1/2 程式碼中沒有 from skeleton.cache import ...？
[ ] query_available_seats 或 execute_booking 中沒有快取呼叫？
```

#### 圖形查詢函式 Checklist

```
[ ] 使用 get_pool()（不是舊版 _driver()）？
[ ] Cypher 使用 node labels 和 relationship types 與 AI_SESSION_CONTEXT.md 一致？
[ ] 種子腳本使用 MERGE 而非 CREATE？
[ ] 找不到路徑時回傳 found=False（不 raise exception）？
```

#### 通用 Checklist

```
[ ] skeleton/config.py、llm_provider.py、seed_vectors.py 沒有被修改？
[ ] skeleton/agent.py 中沒有直接 import psycopg2 / neo4j / databases.*？
[ ] 有對應的測試（至少手動驗證結果）？
[ ] commit 訊息符合 Conventional Commits 格式？
```

### 5.2 給 PR 作者的建議

- **自我審查優先**：送出 PR 前先自己跑過 Checklist
- **小 PR 優於大 PR**：一個 PR 最多 2–3 個函式，超過則拆分
- **留下說明**：對非顯而易見的實作選擇加上行內注釋或 PR 說明
- **測試結果截圖 / 貼上**：讓 reviewer 不需要本地執行也能判斷

### 5.3 Reviewer 溝通禮儀

- 問題型意見：`Question: 這裡為什麼不用 fetchall()?`
- 必修型意見：`Blocker: schedule_id 應作為 WHERE 條件但這裡用了 origin_id，會出錯`
- 建議型意見：`Suggestion: 可以考慮加上 None 型別保護`
- 稱讚：記得肯定好的設計選擇

---

## 6. 開發環境快速設定

```bash
# 1. Clone repo（一次性）
git clone <repo-url>
cd transitflow

# 2. 建立虛擬環境
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # macOS/Linux

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 複製環境設定
cp .env.example .env
# 編輯 .env，填入 DB 連線資訊（見 skeleton/config.py）

# 5. 啟動 Docker 容器（PostgreSQL + Neo4j）
docker compose up -d

# 6. 確認環境正常
docker compose ps
python -c "import psycopg2; print('psycopg2 ok')"
python -c "from neo4j import GraphDatabase; print('neo4j ok')"

# 7. 每次 AI session 開始前
git checkout main && git pull origin main
# 將 AI_SESSION_CONTEXT.md 內容貼入 AI 對話框
```

### 常用快速指令

```bash
# 執行所有測試
pytest tests/ -v --tb=short

# 執行特定函式測試
pytest tests/unit/ -v -k "query_name_here"

# 確認 Docker 狀態
docker compose ps

# 重啟 Docker（遭遇連線問題時）
docker compose down && docker compose up -d
```

---

> 本文件由康睿恩建立，最後更新：2026-05-25。
> 如有任何問題或建議修改，請開 issue 或在群組討論後更新。
