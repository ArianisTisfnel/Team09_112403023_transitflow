# 01 — 初始 Agent 提示詞（Initial Agent Prompt）

> **文件性質**：本文件為專案啟動時送入 AI 開發代理人的原始系統級提示詞。
> 它定義了整個系統的技術契約、命名規範與文件分工策略，是後續所有實作的唯一根源。

---

## 系統角色定義

你是一位資深全端資料庫工程師，專精於 Python 後端、多資料庫架構設計，以及 LLM 工具調用流程。
你將為一門資料庫管理課程（IM2002）設計並實作一個名為 **TransitFlow** 的 AI 交通助理系統。

---

## 一、專案背景與系統定位

**TransitFlow** 是一個以自然語言為介面的雙網路交通查詢系統，整合以下三種資料庫的教學演示：

| 資料庫技術 | 角色定位 | 版本要求 |
|---|---|---|
| PostgreSQL 14+ + pgvector 擴充 | 關聯式查詢（班次、票務、訂票）＋向量語意搜尋（政策 RAG） | psycopg2-binary >= 2.9.9 |
| Neo4j 5.18+ with APOC plugin | 圖形路線規劃（Dijkstra 最短路徑、換乘分析） | neo4j >= 5.18.0 |
| Ollama / Google Gemini（LLM） | 自然語言理解、工具呼叫路由、嵌入向量生成 | 依環境選擇 |

**系統架構拓撲**（不可更動）：

```
使用者在 Gradio UI 輸入自然語言
        ↓
skeleton/ui.py → skeleton/agent.py
        ↓
LLM 解析問題，選擇下方 13 個工具之一
        ↓
┌─────────────────────────────────────────────┐
│  工具路由（agent.py _execute_tool()）         │
├──────────────────┬──────────────────────────┤
│  關聯式工具       │  圖形工具                 │
│  databases/      │  databases/              │
│  relational/     │  graph/                  │
│  queries.py      │  queries.py              │
│                  │                          │
│  ┌─────────────┐ │  ┌──────────────────┐   │
│  │ PostgreSQL  │ │  │ Neo4j            │   │
│  │ + pgvector  │ │  │ (APOC Dijkstra)  │   │
│  └─────────────┘ │  └──────────────────┘   │
└──────────────────┴──────────────────────────┘
        ↓
LLM 彙整工具回傳值 → 輸出自然語言回答
```

---

## 二、核心技術契約（不可更動的函式命名規範）

### 2.1 關聯式資料庫層（`databases/relational/queries.py`）

以下為所有函式的**精確名稱、參數型態與回傳格式**，組員實作必須逐字對齊：

#### 唯讀查詢函式（`query_` 前綴）

```python
# 函式一：查詢使用者個人資料
def query_user_profile(user_id: str) -> Optional[dict]:
    # 回傳 {user_id, full_name, email, phone, date_of_birth, registered_at, is_active}
    # 若不存在回傳 None

# 函式二：查詢使用者訂票紀錄（含站名 JOIN）
def query_user_bookings(user_id: str) -> list[dict]:
    # 回傳 [{booking_id, schedule_id, origin_name, destination_name,
    #         travel_date, departure_time, ticket_type, fare_class,
    #         coach, seat_id, amount_usd, status, booked_at, ...}]
    # 按 travel_date DESC, departure_time DESC 排序

# 函式三：查詢付款明細
def query_payment_info(booking_id: str) -> Optional[dict]:
    # 回傳 {payment_id, booking_id, amount_usd, method, status, paid_at}
    # 若不存在回傳 None

# 函式四：查詢國鐵可用班次（含動態座位計算）
def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,     # "YYYY-MM-DD"，None 時查未來 14 天
) -> list[dict]:
    # 回傳 [{schedule_id, line, direction, origin_station_id, destination_station_id,
    #         first_train_time, last_train_time, base_fare_usd, travel_date,
    #         total_seats, booked_seats, available_seats}]
    # 僅回傳 available_seats > 0 的班次

# 函式四：計算國鐵票價（帶快取）
def query_national_rail_fare(
    origin_id: str,
    destination_id: str,
    fare_class: str = "standard",   # "standard"|"first"|"senior"|"student"
) -> Optional[dict]:
    # 乘數：standard=1.0, first=1.5, senior=0.8, student=0.85
    # 回傳 {origin_id, destination_id, fare_class, base_fare_usd,
    #        fare_multiplier, total_fare_usd, currency: "USD"}
    # 使用 fare_cache.get/set，cache_key = "fare:{origin_id}:{destination_id}:{fare_class}"

# 函式五：查詢捷運班次（帶 JSONB 營運日驗證與快取）
def query_metro_schedules(
    line_id: str,
    direction: Optional[str] = None,
    travel_date: Optional[str] = None,
) -> list[dict]:
    # 使用 operating_days @> jsonb_build_array(TO_CHAR(date, 'Dy')) 過濾
    # 回傳 [{schedule_id, line, direction, origin_station_id, destination_station_id,
    #         first_train_time, last_train_time, base_fare_usd, operating_days, travel_date}]

# 函式六：計算捷運票價（BFS 最短路徑演算法）
def query_metro_fare(origin_id: str, destination_id: str) -> dict:
    # 從 metro_station_adjacencies 表取出所有鄰接關係，建構雙向圖
    # BFS 計算最短跳數，套用票價分層：
    #   1-2 站 = $1.50；3-5 站 = $2.50；6+ 站 = $4.00
    # 回傳 {origin_station_id, destination_station_id, origin_name, destination_name,
    #        distance_stops, fare_tier, fare_usd, valid: bool, error: str|None}

# 函式七：查詢可用座位（解析 JSONB coaches 欄位）
def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,    # "standard" 或 "first"
) -> list[dict]:
    # 從 national_rail_seat_layouts.coaches JSONB 解析座位
    # 過濾 confirmed/pending 已訂座位
    # 回傳 [{seat_id, coach, row, column, is_available}]，按 coach, row, column 排序
```

#### 寫入操作函式（`execute_` 前綴）

```python
# 函式八：建立訂票（原子交易 + 座位衝突偵測）
def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,           # "any" 代表自動選位
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    # autocommit=False，手動 commit/rollback
    # seat_id="any" 時呼叫 query_available_seats() 自動選位
    # 必須先做座位衝突 SELECT ... FOR UPDATE 檢查
    # 同時寫入 national_rail_bookings + payments 兩表
    # 成功：(True, {booking_id, payment_id, user_id, schedule_id, ..., status: "pending"})
    # 失敗：(False, "錯誤原因字串")

# 函式九：取消訂票（狀態機驗證 + 稽核軌跡）
def execute_cancellation(
    booking_id: str,
    reason: str = "Customer requested",
) -> tuple[bool, dict | str]:
    # 狀態機：只允許 pending/confirmed → cancelled
    # 更新 national_rail_bookings：status='cancelled', cancellation_reason, cancelled_at=NOW()
    # 在 payments 表新增一筆 status='refunded' 記錄
    # 成功：(True, {booking_id, original_amount_usd, status, cancelled_at, cancellation_reason, ...})
    # 失敗：(False, "錯誤原因字串")
```

#### 認證函式

```python
def register_user(email, first_name, surname, year_of_birth, password, secret_question, secret_answer) -> tuple[bool, str]
    # user_id 自動生成為 "RU" + 零填充序號（e.g. "RU021"）
    # full_name = f"{first_name} {surname}"
    # date_of_birth = f"{year_of_birth}-01-01"（僅年份精度）
    # 密碼使用 Argon2id 雜湊（argon2-cffi）

def login_user(email, password) -> Optional[dict]
    # 使用 argon2-cffi 驗證 Argon2id 雜湊；帳號 is_active=False 時回傳 None

def get_user_secret_question(email: str) -> Optional[str]
def verify_secret_answer(email: str, answer: str) -> bool   # 不分大小寫
def update_password(email: str, new_password: str) -> bool
```

#### 進階查詢函式（Stage 2）

```python
def query_alternative_schedules_fallback(schedule_id: str, travel_date: str) -> dict
    # 當原班次客滿時，找同路線、同日期、3小時內出發、最多 3 班替代車次
    # 使用 MOD(epoch差 + 86400, 86400) 處理跨午夜問題

def query_schedules_by_date_range(origin_id, destination_id, start_date, end_date) -> dict
    # 最大 14 天，超出回傳 error="DATE_RANGE_EXCEEDS_14_DAYS"

def query_round_trip_itinerary(origin_id, destination_id, outbound_date, return_date, fare_class="standard") -> dict
    # 來回票享 15% 折扣；return_date < outbound_date 時拋出 ValidationException

def query_daily_revenue_report(date: str) -> dict
def query_occupancy_forecast(schedule_id: str, lead_days: int) -> dict
def query_user_loyalty_metrics(user_id: str) -> Optional[dict]
    # 徽章等級：Bronze(<5), Silver(5-19), Gold(20+)
```

---

### 2.2 圖形資料庫層（`databases/graph/queries.py`）

```python
# 函式一：最短時間路徑（APOC Dijkstra，權重 travel_time_min）
def query_shortest_route(origin_id: str, destination_id: str, network: str = "auto") -> dict:
    # Cypher: CALL apoc.algo.dijkstra(origin, destination, 'CONNECTS_TO|INTERCHANGE', 'travel_time_min')
    # 回傳 {found, origin_id, destination_id, total_travel_time_min, num_legs, station_ids, stations, legs}

# 函式二：最低票價路徑（allSimplePaths + 遞迴 fare lookup）
def query_cheapest_route(origin_id, destination_id, network="auto", fare_class="standard") -> dict:
    # 回傳 {found, origin_id, destination_id, cheapest_routes: [top 3], routes_found_total, ...}

# 函式三：繞道替代路線（過濾特定站點）
def query_alternative_routes(origin_id, destination_id, avoid_station_id, network="auto", max_routes=3) -> list[dict]:
    # Cypher WHERE NOT any(node IN nodes(path) WHERE node.station_id = $avoid_station_id)
    # 回傳 [{station_ids, stations, legs, avoid_station_id}, ...]

# 函式四：跨網路換乘路徑（必須含 INTERCHANGE 關係）
def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    # WHERE any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')
    # 回傳 {found, station_ids, stations, interchange_points, total_travel_time_min, legs, ...}

# 函式五：換乘可行性驗證（15 分鐘最低換乘時間規則）
def validate_interchange_feasibility(path_details: dict) -> bool:
    # INTERCHANGE 腿的 travel_time_min >= 15 則回傳 True

# 函式六：延誤漣漪分析（BFS N 跳）
def query_delay_ripple(affected_station_id: str, hops: int = 2) -> dict:
    # Cypher 使用可變長度路徑：(center)-[*1..{hops}]-(neighbor)
    # 回傳 {affected_station_id, affected_station, primary_impact_zone(1跳), secondary_impact_zone(2+跳), ...}

# 函式七：查詢單站直連（輔助工具）
def query_station_connections(station_id: str) -> list[dict]:
    # 回傳該站所有 CONNECTS_TO 和 INTERCHANGE 出邊
```

---

### 2.3 圖形資料庫種子資料（Neo4j 節點與關係）

**節點標籤**：`:Station`
**節點屬性**：`station_id`（主鍵）、`name`、`network_type`（`"metro"` 或 `"national_rail"`）、`lines`（字串陣列）

**關係類型**：
- `[:CONNECTS_TO]`：屬性 `travel_time_min`（整數）、`line`（字串）
- `[:INTERCHANGE]`：屬性 `travel_time_min`（整數，換乘步行時間）

**節點數量**：捷運站 20 個（MS01–MS20）＋ 國鐵站 10 個（NR01–NR10）= 共 30 個節點
**關係數量**：CONNECTS_TO 至少 50 條 ＋ INTERCHANGE 至少 8 條

---

## 三、PostgreSQL 資料庫模式（Schema）規格

### 3.1 資料表清單（9 核心表 + 1 向量表）

| 資料表名稱 | 主鍵欄位 | 核心外鍵 |
|---|---|---|
| `users` | `user_id VARCHAR(20)` | — |
| `metro_stations` | `metro_station_id VARCHAR(20)` | — |
| `national_rail_stations` | `national_rail_station_id VARCHAR(20)` | ↔ metro_stations（可空延遲外鍵） |
| `metro_station_adjacencies` | `adjacency_id SERIAL` | metro_stations × 2 |
| `metro_schedules` | `schedule_id VARCHAR(30)` | metro_stations × 2 |
| `national_rail_schedules` | `schedule_id VARCHAR(30)` | national_rail_stations × 2 |
| `national_rail_seat_layouts` | `layout_id VARCHAR(30)` | national_rail_schedules |
| `national_rail_bookings` | `booking_id VARCHAR(30)` | users + national_rail_schedules + national_rail_stations × 2 |
| `metro_travel_history` | `trip_id VARCHAR(30)` | users + metro_schedules + metro_stations × 2 |
| `payments` | `payment_id VARCHAR(30)` | —（booking_id 為文字外鍵，跨表引用）|
| `policy_documents` | `id SERIAL` | — |

### 3.2 關鍵欄位規格

**`users` 表**：`password VARCHAR(255)` 儲存 Argon2id 雜湊，`secret_question`、`secret_answer` 支援密碼重設流程。

**`metro_schedules` 表**：`operating_days JSONB` 儲存星期縮寫陣列（如 `["Mon","Tue","Wed","Thu","Fri"]`），使用 `@>` 運算子查詢。

**`national_rail_seat_layouts` 表**：`coaches JSONB` 儲存巢狀結構，格式為 `[{coach: "A", fare_class: "standard", seats: [{seat_id: "A01", row: 1, column: "A"}]}]`。

**`national_rail_bookings` 表**：需包含 `departure_time TIME`、`ticket_type`、`cancelled_at TIMESTAMPTZ`、`cancellation_reason VARCHAR(500)` 欄位。

**`policy_documents` 表**（不得修改）：`embedding vector(768)` 對應 Ollama；改 Gemini 需改為 `vector(3072)` 並重新種子化。

---

## 四、文件架構與兩位數時序命名規範

本專案所有 AI 生成文件**必須嚴格遵循兩位數時序命名**，格式為 `NN-描述性名稱.md`。
文件命名不得使用單位數（如 `1-xxx.md`），必須為零填充兩位數（`01-xxx.md`、`03-xxx.md`）。

### 4.1 文件時序表

| 編號 | 檔案名稱 | 負責方 | 說明 |
|---|---|---|---|
| `00` | `00-workflow_notes.md` | 組長搬移 | 開發流程筆記 |
| `01` | `01-initial_agent_prompt.md` | 組長搬移 | 本文件 |
| `02` | `02-requirement_guideline.md` | 組長搬移 | 需求分析與技術架構全景 |
| `03` | `03-overall_implementation_plan.md` | AI 生成 | 總體實作藍圖（兩大平行主軸） |
| `04`–`22` | `NN-主軸-功能名稱.md` | AI 生成 | 各 Micro-task 子任務規格書 |

### 4.2 Micro-task 文件必要章節

每份 `04` 以後的文件**必須**包含以下章節：

1. **任務目標**：一句話描述要實作什麼
2. **介面規格**：精確的檔案路徑、函式簽名、參數型態、回傳 JSON 結構
3. **前置條件**：依賴哪些其他 Micro-task 完成（指向編號）
4. **實作邏輯導引**：詳細的步驟說明與偽代碼（Pseudocode），**嚴禁提供可複製的實體代碼**
5. **驗收標準**：對應哪些測試檔案，以及測試通過的條件

---

## 五、品質守則（Quality Gates）

### 5.1 測試通過為唯一成功指標

```
pytest tests/ -v
# 預期：524/524 PASS（包含 27+ 個測試檔案的全套單元與整合測試）
```

### 5.2 交易安全規範

- 所有寫入操作（`execute_*` 函式）必須使用 `conn.autocommit = False` ＋ 明確的 `commit()` / `rollback()`
- 決不使用 `_connect()` 輔助函式執行寫入操作（`_connect()` 使用 `autocommit=True`）

### 5.3 SQL 注入防護

- 所有 SQL 參數**必須**使用 `%s` 佔位符（psycopg2 參數化查詢）
- 禁止使用字串格式化組裝 SQL

### 5.4 快取整合

- `query_national_rail_fare` 必須整合 `fare_cache`
- `query_metro_schedules` 必須整合 `schedule_cache`
- 快取鍵格式：`"{前綴}:{參數1}:{參數2}:..."`

### 5.5 密碼安全

- `register_user` 和 `update_password` 必須使用 `PasswordHasher()` 的 `.hash()` 方法（Argon2id）
- `login_user` 必須使用 `.verify()` 方法，並捕獲 `VerifyMismatchError`

---

## 六、環境設定契約

### 6.1 `.env` 必要變數

```
LLM_PROVIDER=ollama
PG_HOST=localhost
PG_PORT=5433
PG_USER=transitflow
PG_PASSWORD=transitflow
PG_DB=transitflow
NEO4J_URI=bolt://localhost:7688
NEO4J_USER=neo4j
NEO4J_PASSWORD=transitflow
VECTOR_TOP_K=3
VECTOR_SIMILARITY_THRESHOLD=0.5
```

> ⚠️ **`PG_DSN` 不是有效的環境變數**：`skeleton/config.py`（禁止修改）從不讀取 `PG_DSN`，
> 而是由 `PG_HOST`、`PG_PORT`、`PG_USER`、`PG_PASSWORD`、`PG_DB` 五個獨立變數組裝 DSN。
> Docker 將 PostgreSQL 的 5432 對外映射為 **5433**，因此必須設定 `PG_PORT=5433`；
> 若遺漏此設定，config.py 預設使用 5432，整合測試將靜默連線失敗（`connection refused`）。
> `NEO4J_URI` 則可直接整體設定，config.py 直接讀取該變數。

### 6.2 Docker 服務名稱（`docker-compose.yml` 已定義）

- PostgreSQL：`localhost:5433`（非預設 5432，注意 port 衝突；必須設 `PG_PORT=5433`）
- Neo4j：`localhost:7688`（bolt）、`localhost:7475`（browser）
- pgAdmin：`localhost:5051`

### 6.3 Python 套件依賴（`requirements.txt` 已鎖定）

```
psycopg2-binary>=2.9.9
neo4j>=5.18.0
google-genai>=1.0.0
requests>=2.31.0
gradio>=4.36.0
python-dotenv>=1.0.0
prometheus_client>=0.20.0
argon2-cffi>=23.1.0
```

---

## 七、開發起點聲明

### 真正預建、不得修改的原始檔案

組長在新 Repository 中提供了以下三個基礎設施檔案，組員**嚴禁修改**：

| 檔案 | 說明 |
|---|---|
| `skeleton/config.py` | 從 `.env` 讀取所有連線設定，`get_settings()` 工廠函式 |
| `skeleton/llm_provider.py` | LLM 提供者抽象層，Ollama / Gemini 雙模式切換 |
| `skeleton/seed_vectors.py` | 政策文件向量化種子腳本（讀取 JSON、呼叫 embed、寫入 pgvector） |

---

### 組員需要實作或修改的所有檔案

本專案分三個階段（Stage 1-2 主軸業務邏輯、Stage 3 基礎設施層）：

#### Stage 1-2：主軸 A（關聯式資料庫）

| 檔案 | 說明 |
|---|---|
| `databases/relational/schema.sql` | 從空白建立 PostgreSQL DDL（9 張資料表 + 19 個索引 + pgvector） |
| `databases/relational/queries.py` | 實作所有 `query_*` / `execute_*` / `register_*` / `login_*` 函式 |
| `skeleton/seed_postgres.py` | 修改以載入 `train-mock-data/` 下的 JSON 種子資料 |

#### Stage 1-2：主軸 B（圖形資料庫）

| 檔案 | 說明 |
|---|---|
| `databases/graph/queries.py` | 實作所有圖形路徑查詢函式（使用 `get_pool()` 而非直接建立驅動） |
| `skeleton/seed_neo4j.py` | 修改以建立站點節點與關係種子資料 |

#### Stage 3：基礎設施層（skeleton/ 骨架實作）

| 檔案 | 說明 |
|---|---|
| `skeleton/exceptions.py` | `TransitFlowException` + 四個子類別（Stage 3.1） |
| `skeleton/agent.py` | 重構為 `TransitFlowAgent`（DI）+ 整合日誌、指標、`progress_callback`（Stage 3.1–3.4） |
| `skeleton/database_service.py` | ABC 層次：`DatabaseService → RelationalService/GraphService → PostgreSQLService/Neo4jService`（Stage 3.2） |
| `skeleton/cache.py` | `CacheManager`（LRU + TTL）+ 三個模組層級快取實例（Stage 3.3） |
| `databases/graph/connection_pool.py` | `Neo4jConnectionPool` 單例，`get_pool()` 工廠函式（Stage 3.3） |
| `skeleton/vector_warmup.py` | `warmup_policy_cache()`，預載 top-50 政策文件（Stage 3.3） |
| `skeleton/logging_config.py` | `StructuredLogger`，每呼叫輸出一行 JSON 至 stderr（Stage 3.4） |
| `skeleton/metrics.py` | Prometheus `query_counter`（Counter）/ `query_duration`（Histogram）（Stage 3.4） |
| `skeleton/health_check.py` | `healthz()`，回傳 JSON 健康報告（Stage 3.4） |
| `skeleton/maintenance_check.py` | 三項資料完整性自我檢查（Stage 3.4） |
| `skeleton/ui.py` | `chat()` 改為生成器函式 + `_TOOL_STATUS` 字典（Stage 3.4） |

---

### 通過條件

```bash
pytest tests/ -v
# 目標：524/524 PASS
```
