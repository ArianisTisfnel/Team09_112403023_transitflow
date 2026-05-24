# 03 — 總體實作藍圖（Overall Implementation Plan）

> **文件性質**：本文件銜接 `02-requirement_guideline.md`（需求規格）與 `tests/`（驗收測試套件），
> 宏觀定義整個實作任務的拆分策略與分工架構。
> 本文件是所有 `04`–`22` Micro-task 子任務規格書的父文件。

---

## 一、專案架構全景

### 完整目錄結構

```
TransitFlow/
├── agent.py                        ← 主入口（Gradio UI 啟動）
├── docker-compose.yml              ← 三資料庫容器配置（PostgreSQL + Neo4j）
├── requirements.txt                ← psycopg2、neo4j、argon2-cffi、pgvector 等
│
├── skeleton/                       ← 框架層（config.py/llm_provider.py/seed_vectors.py 禁止修改；agent.py/ui.py 需於 Stage 3 修改）
│   ├── agent.py                    ← LLM tool-calling 代理（工具選擇 + 結果正規化）
│   ├── cache.py                    ← fare_cache / schedule_cache（LRU + TTL=300s）
│   ├── config.py                   ← 從 .env 讀取連線設定
│   ├── database_service.py         ← RelationalService / GraphService SOLID 抽象
│   ├── exceptions.py               ← ValidationException、DatabaseException 等定義
│   ├── health_check.py             ← 三資料庫健康檢查
│   ├── llm_provider.py             ← LLM 提供者抽象（Ollama / Gemini）
│   ├── logging_config.py           ← StructuredLogger JSON 日誌
│   ├── maintenance_check.py        ← 資料完整性自我檢查
│   ├── metrics.py                  ← query_counter / query_duration（Prometheus）
│   ├── seed_neo4j.py               ← Neo4j 種子資料載入器（可直接執行）
│   ├── seed_postgres.py            ← PostgreSQL 種子資料載入器（可直接執行）
│   ├── seed_vectors.py             ← 政策文件向量化種子腳本
│   ├── ui.py                       ← Gradio 介面
│   └── vector_warmup.py            ← 向量索引暖機工具
│
├── databases/
│   ├── relational/                 ← ★ 主軸 A（組員實作）
│   │   ├── schema.sql              ← DDL（9 核心資料表 + 19 個索引 + pgvector）
│   │   └── queries.py             ← 19 個查詢 / 寫入函式
│   └── graph/                     ← ★ 主軸 B（組員實作）
│       ├── connection_pool.py     ← Neo4j 連線池（Stage 3.3 實作，見 25-stage3.3-performance-boost.md）
│       └── queries.py             ← 8 個圖形路徑查詢函式（使用 get_pool()）
│
├── train-mock-data/               ← JSON 種子資料（唯讀，禁止修改）
│   ├── metro_stations.json
│   ├── national_rail_stations.json
│   ├── national_rail_schedules.json
│   ├── national_rail_seat_layouts.json
│   ├── metro_schedules.json
│   ├── policy_documents.json
│   └── ...
│
├── docs/
│   └── refactored_plan/           ← 本實作指南目錄
│
└── tests/
    ├── unit/                      ← 單元測試（mock 資料庫連線）
    └── integration/               ← 整合測試（需真實資料庫連線）
```

### 系統核心（資料流）

TransitFlow 由三個資料庫層組成，彼此並行但各司其職：

```
┌─────────────────────────────────────────────────────────┐
│        skeleton/（初始骨架；Stage 3 會修改 agent.py/ui.py）│
│   agent.py  ←→  llm_provider.py  ←→  ui.py             │
│   cache.py  /  exceptions.py  /  database_service.py   │
│   logging_config.py  /  metrics.py  /  health_check.py  │
└────────────────────┬────────────────────────────────────┘
                     │ 工具呼叫
          ┌──────────┴──────────┐
          ▼                     ▼
┌─────────────────┐    ┌──────────────────┐
│  主軸 A（關聯式）│    │  主軸 B（圖形）   │
│                 │    │                  │
│  PostgreSQL     │    │  Neo4j           │
│  + pgvector     │    │  (APOC plugin)   │
│                 │    │                  │
│ schema.sql      │    │ seed_neo4j.py    │
│ queries.py      │    │ queries.py       │
└─────────────────┘    └──────────────────┘
```

### 組員必須實作的檔案（分三階段）

#### Stage 1–2：業務邏輯層

| 檔案路徑 | 負責主軸 | 內容 |
|---|---|---|
| `databases/relational/schema.sql` | 主軸 A | PostgreSQL DDL（9 核心表 + 索引 + pgvector 擴充） |
| `databases/relational/queries.py` | 主軸 A | 所有 `query_*` 和 `execute_*` 函式實作 |
| `skeleton/seed_postgres.py` | 主軸 A | 修改以載入 `train-mock-data/` JSON 種子資料 |
| `databases/graph/queries.py` | 主軸 B | 所有圖形路線查詢函式實作（依賴 `skeleton/seed_neo4j.py` 已載入的節點與關係） |
| `skeleton/seed_neo4j.py` | 主軸 B | 修改以建立站點節點與關係種子資料 |

#### Stage 3：基礎設施層（skeleton/ 骨架實作）

| 檔案路徑 | 說明 |
|---|---|
| `skeleton/exceptions.py` | 新建：`TransitFlowException` + 四個子類別（見 23） |
| `skeleton/agent.py` | 修改：重構為 `TransitFlowAgent` DI + 整合日誌、指標（見 23–24–26） |
| `skeleton/database_service.py` | 新建：ABC 服務層（見 24） |
| `skeleton/cache.py` | 新建：`CacheManager` + 三個快取實例（見 25） |
| `databases/graph/connection_pool.py` | 新建：`Neo4jConnectionPool` 單例（見 25）|
| `skeleton/vector_warmup.py` | 新建：`warmup_policy_cache()`（見 25） |
| `skeleton/logging_config.py` | 新建：`StructuredLogger`（見 26） |
| `skeleton/metrics.py` | 新建：Prometheus 指標（見 26） |
| `skeleton/health_check.py` | 新建：`healthz()`（見 26） |
| `skeleton/maintenance_check.py` | 新建：三項完整性自我檢查（見 26） |
| `skeleton/ui.py` | 修改：`chat()` 改為生成器（見 26） |

---

## 二、平行分工策略

### 2.1 分工原則

本專案採用**技術層次平行拆分**策略：

- **主軸 A（關聯式資料庫）**：負責所有結構化業務邏輯，技術棧以 SQL + psycopg2 為主，涵蓋 DDL 設計、交易管理、快取整合、BFS 演算法、向量搜尋。

- **主軸 B（圖形資料庫）**：負責所有網路拓撲分析，技術棧以 Cypher + APOC 為主，涵蓋圖形種子資料設計、Dijkstra 路徑規劃、BFS 漣漪分析。

### 2.2 工作量等價驗證

| 指標 | 主軸 A | 主軸 B |
|---|---|---|
| 需實作函式數 | 19 個（含認證、進階、分析） | 8 個（含複雜路徑演算法） |
| SQL/Cypher 複雜度 | 中（CTE、CROSS JOIN、JSONB 解析） | 高（APOC 插件、可變長度路徑、圖遍歷） |
| 資料量設計 | 9 張資料表 + 19 個索引 | 30 個節點 + 60+ 條關係 |
| 測試覆蓋檔案數 | 17 個 test 檔案 | 8 個 test 檔案 |
| 預估開發時間 | 中等（邏輯複雜度分散於多函式） | 中等（APOC 學習成本較高，但函式少） |

**結論**：主軸 A 以廣度取勝（函式多、邏輯細碎），主軸 B 以深度取勝（每個函式涉及複雜圖演算法），兩者難度對等。

---

## 三、實作時序與依賴關係

### 3.1 關鍵依賴鏈

```
[主軸 A 依賴鏈]
04（基礎表 DDL）
 └─→ 05（進階表 DDL + 索引）
      └─→ 06（使用者/訂票查詢）← 需要 users + bookings 表
           └─→ 07（國鐵可用班次）← 需要 schedules + seat_layouts + bookings 表
                └─→ 08（票價計算）← 需要 schedules 表
                     └─→ 09（捷運票價 BFS ＋ 可用座位查詢）← 需要 metro_station_adjacencies + seat_layouts + bookings 表
                          ├─→ 10（建立訂票）← 依賴 query_available_seats（09 中已實作）
                          └─→ 11（取消訂票）← 依賴 bookings 表結構
                               └─→ 12（認證函式）← 依賴 users 表

                               21（進階查詢）← 依賴 07、08
                               22（分析函式）← 依賴 07、09、10

[主軸 B 依賴鏈]
13（節點種子）
 └─→ 14（CONNECTS_TO 關係種子）
      └─→ 15（INTERCHANGE 關係種子）
           ├─→ 16（Dijkstra 最短路徑）
           ├─→ 17（替代路線）
           ├─→ 18（換乘路徑 + 可行性驗證）
           ├─→ 19（延誤漣漪分析）
           └─→ 20（最低票價路徑）

[跨主軸依賴]
20（最低票價路徑）← 需要呼叫主軸 A 的 query_national_rail_fare + query_metro_fare

[Stage 3 依賴鏈]
23（異常層）
 └─→ 24（SOLID 服務層 + TransitFlowAgent）
      └─→ 25（CacheManager + Neo4jConnectionPool + 暖機）
           │    ↑
           │    整合到主軸 A 的 query_national_rail_fare / query_metro_schedules
           │    整合到主軸 B 的 connection_pool.py（get_pool()）
           └─→ 26（StructuredLogger + Prometheus + UI 生成器）
```

### 3.2 可平行執行的節點

在不衝突的前提下，以下任務可同時開發：

- 主軸 A 的 `04`–`05`（DDL）可與主軸 B 的 `14`–`16`（Neo4j 種子）同時進行
- 主軸 A 的 `12`（認證函式）可與主軸 B 的 `17`–`20` 同時進行

---

## 四、Micro-task 文件目錄

### 主軸 A — 關聯式資料庫

| 編號 | 檔案名稱 | 核心任務 |
|---|---|---|
| `04` | `04-A-schema-core-tables.md` | `users`、`metro_stations`、`national_rail_stations`、`metro_station_adjacencies` DDL |
| `05` | `05-A-schema-transit-tables.md` | `metro_schedules`、`national_rail_schedules`、`national_rail_seat_layouts`、`national_rail_bookings`、`metro_travel_history`、`payments`、所有索引、pgvector |
| `06` | `06-A-query-user-profile-bookings.md` | `query_user_profile`、`query_user_bookings`、`query_payment_info` |
| `07` | `07-A-query-nr-availability.md` | `query_national_rail_availability`（單日 + 14 天窗口） |
| `08` | `08-A-query-nr-fare-metro-schedules.md` | `query_national_rail_fare`（含快取）、`query_metro_schedules`（含 JSONB 營運日）|
| `09` | `09-A-query-metro-fare-seats.md` | `query_metro_fare`（BFS 演算法）、`query_available_seats`（JSONB 解析） |
| `10` | `10-A-execute-booking.md` | `execute_booking`（原子交易、自動選位、座位衝突偵測） |
| `11` | `11-A-execute-cancellation.md` | `execute_cancellation`（狀態機驗證、稽核軌跡） |
| `12` | `12-A-auth-functions.md` | `register_user`、`login_user`、`get_user_secret_question`、`verify_secret_answer`、`update_password` |

### 主軸 B — 圖形資料庫

| 編號 | 檔案名稱 | 核心任務 |
|---|---|---|
| `13` | `13-B-neo4j-seed-stations.md` | `:Station` 節點種子（MS01–MS20 + NR01–NR10） |
| `14` | `14-B-neo4j-seed-connections.md` | `CONNECTS_TO` 關係種子（M1–M4 + NR1–NR2 所有邊） |
| `15` | `15-B-neo4j-seed-interchange.md` | `INTERCHANGE` 關係種子（8+ 跨網路換乘點） |
| `16` | `16-B-query-shortest-route.md` | `query_shortest_route`（APOC Dijkstra）、`query_station_connections` |
| `17` | `17-B-query-alternative-routes.md` | `query_alternative_routes`（allSimplePaths + 節點過濾） |
| `18` | `18-B-query-interchange-path.md` | `query_interchange_path`、`validate_interchange_feasibility` |
| `19` | `19-B-query-delay-ripple.md` | `query_delay_ripple`（BFS 主次影響區分類） |
| `20` | `20-B-query-cheapest-route.md` | `query_cheapest_route`（allSimplePaths + 跨模組票價計算） |

### 進階功能（Stage 2）

| 編號 | 檔案名稱 | 核心任務 |
|---|---|---|
| `21` | `21-adv-fallback-date-range.md` | `query_alternative_schedules_fallback`、`query_schedules_by_date_range` |
| `22` | `22-adv-round-trip-analytics.md` | `query_round_trip_itinerary`、`query_daily_revenue_report`、`query_occupancy_forecast`、`query_user_loyalty_metrics` |

### Stage 3 — 基礎設施層

| 編號 | 檔案名稱 | 核心任務 |
|---|---|---|
| `23` | `23-stage3.1-exception-layer.md` | `skeleton/exceptions.py`（`TransitFlowException` + 4 子類別）+ `@error_handler` 裝飾器 |
| `24` | `24-stage3.2-solid-refactor.md` | `skeleton/database_service.py`（ABC 層次）+ `skeleton/agent.py`（`TransitFlowAgent` DI 重構） |
| `25` | `25-stage3.3-performance-boost.md` | `skeleton/cache.py`（`CacheManager`）+ `databases/graph/connection_pool.py`（`Neo4jConnectionPool`）+ `skeleton/vector_warmup.py` |
| `26` | `26-stage3.4-ui-observability.md` | `skeleton/logging_config.py`、`skeleton/metrics.py`、`skeleton/health_check.py`、`skeleton/maintenance_check.py`、`skeleton/ui.py`（生成器 `chat()`） |

---

## 五、驗收標準（DoD）

### 主軸 A 各函式通過確認

主軸 A 的每個 Micro-task 完成後，執行對應的單元測試：

```bash
# 依函式名稱篩選，快速驗收單一函式
pytest tests/unit/ -v -k "user_profile"
pytest tests/unit/ -v -k "user_bookings"
pytest tests/unit/ -v -k "national_rail_availability"
pytest tests/unit/ -v -k "national_rail_fare"
pytest tests/unit/ -v -k "metro_schedules"
pytest tests/integration/ -v -k "metro_fare"
pytest tests/unit/ -v -k "available_seats"
pytest tests/unit/ -v -k "execute_booking"
pytest tests/unit/ -v -k "execute_cancellation"
pytest tests/unit/ -v -k "register or login or auth"
```

### 主軸 B 各函式通過確認

```bash
# query_shortest_route — 無 unit test，直接用整合測試驗收
pytest tests/integration/test_phase_2.5_gap_fill_integration.py -v -k "shortest_route"
pytest tests/unit/ -v -k "interchange_path"
pytest tests/unit/ -v -k "interchange_feasibility"
pytest tests/integration/ -v -k "delay_ripple"
pytest tests/integration/ -v -k "delay_ripple or shortest_route or interchange"
```

> ⚠️ **`query_shortest_route` 無 unit test**：`tests/unit/` 下沒有 shortest_route 相關測試；
> `pytest tests/unit/ -v -k "shortest_route"` 會收集到 **0 筆**（pytest 不報錯，但什麼都沒驗到）。
> 請直接使用整合測試命令：
> `pytest tests/integration/test_phase_2.5_gap_fill_integration.py -v -k "shortest_route"`
> （對應 `TestQueryShortestRouteIntegration`，共 5 個測試）。

> ⚠️ **`query_delay_ripple` 無獨立 unit test**：`tests/unit/` 下沒有 `delay_ripple` 命名的功能性測試
> 檔案；`pytest tests/unit/ -v -k "delay_ripple"` 只會收集到 Stage 3.2 的委派測試，
> 不驗證函式本身邏輯。請改用 `pytest tests/integration/ -v -k "delay_ripple"` 驗收，
> 共有 4 個整合測試（位於 `tests/integration/test_phase_1.3.2.5_query_delay_ripple.py`）。

### 進階功能通過確認

```bash
pytest tests/unit/ -v -k "alternative_schedules_fallback"
pytest tests/unit/ -v -k "schedules_by_date_range"
pytest tests/unit/ -v -k "round_trip_itinerary"
pytest tests/unit/ -v -k "revenue_report or occupancy_forecast or loyalty_metrics"
```

### Stage 3 通過確認

```bash
pytest tests/unit/ -v -k "exception_layer"
pytest tests/unit/ -v -k "solid_refactor"
pytest tests/unit/ -v -k "performance_boost"
pytest tests/unit/ -v -k "ui_observability"
```

### 全套驗收條件（最終門禁）

```bash
pytest tests/ -v
# 目標：524/524 PASS
```

---

## 六、設計決策備忘

| 決策 | 理由 |
|---|---|
| `operating_days` 使用 JSONB 陣列而非正規化表 | 避免過度設計（星期欄位固定為 7 個，JSONB 提供靈活的「部分運營日」查詢） |
| `coaches` 使用 JSONB 而非 `coach_seats` 關係表 | 座位佈局結構在載入後唯讀，JSONB 效能優於多次 JOIN |
| BFS 用於捷運票價計算而非 SQL RECURSIVE | 捷運站點數固定（20 個），Python BFS 比 PostgreSQL 遞迴 CTE 更易調試 |
| `execute_*` 手動管理 `autocommit=False` | `_connect()` 使用 autocommit=True 不適用於寫入場景；交易安全需明確控制 |
| Neo4j 使用 `MERGE` 而非 `CREATE` | 支援種子資料的冪等重入（重複執行不產生重複節點） |
| INTERCHANGE 關係採用 `travel_time_min=15` | 反映現實換乘步行時間；`validate_interchange_feasibility` 驗證此閾值 |
| `error_handler` 捕捉 generic `Exception` 時不包含 message | 防止內部系統細節外洩（安全考量） |
| `Neo4jConnectionPool.__exit__` 不關閉 driver | 連線池設計為常駐服務，關閉後無法自動重建 |
| `query_available_seats` / `execute_booking` 不使用任何快取 | 即時座位狀態不可快取，否則超賣風險 |
| `chat()` 改為生成器函式（yield） | 讓 UI 在 agent 執行期間即時更新，避免介面凍結 |
