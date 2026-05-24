# TransitFlow 專案進度導引

## 一、技術架構全景

### 核心系統功能
TransitFlow 是一個**雙網路智能運輸助手**，整合三類不同資料庫技術，為用戶提供統一的自然語言查詢介面。

```
┌─────────────────────────────────────────────────────────────┐
│                    Gradio Web UI 層                         │
│                 (skeleton/ui.py)                            │
└───────────────┬───────────────────────────────────────────┘
                │
┌───────────────▼───────────────────────────────────────────┐
│                   LLM Agent 層                             │
│         (skeleton/agent.py)                                │
│    ┌─ Gemini (Google Gen AI) / Ollama (Local)          │
│    └─ Tool Routing & Function Calling                  │
└───────────┬─────────────┬─────────────┬──────────────────┘
            │             │             │
    ┌───────▼──────┐  ┌──▼──────────┐  ┌──▼──────────────┐
    │ PostgreSQL   │  │PostgreSQL   │  │    Neo4j        │
    │(Relational)  │  │+ pgvector   │  │   (Graph DB)    │
    │              │  │  (Vector)   │  │                 │
    │ Stations,    │  │             │  │ Network Paths,  │
    │ Schedules,   │  │ Policies &  │  │ Route Finding,  │
    │ Bookings,    │  │ Documents   │  │ Interchange     │
    │ Seats, Users │  │ (RAG)       │  │ Logic           │
    └──────────────┘  └─────────────┘  └─────────────────┘
```

### 技術棧詳解

| 層級 | 技術 | 用途 | 狀態 |
|------|------|------|------|
| **前端** | Gradio 4.36+ | Web UI + 聊天介面 | ✅ 已完成 |
| **LLM 引擎** | Google Gemini / Ollama | 自然語言理解 & Tool Routing | ✅ 已完成 |
| **關係型 DB** | PostgreSQL 14+ | 結構化運輸數據（站點、班次、訂單） | ❌ 待設計 |
| **向量 DB** | PostgreSQL + pgvector | 語義搜尋政策文件 | ✅ 框架就位 |
| **圖數據庫** | Neo4j 5.18+ | 路徑尋找、網路拓樸 | ❌ 待設計 |
| **後端架構** | Python 3.9+ | 查詢函數、資料聚合 | 🟡 部分完成 |

### 核心功能流程
1. **問題理解**：使用者輸入自然語言問題
2. **工具路由**：LLM 分析問題，選擇調用的資料庫查詢工具
3. **並行查詢**：同時對 PostgreSQL、pgvector、Neo4j 執行相應查詢
4. **結果規範化**：將異質資料轉換成結構化文字
5. **智能回應**：LLM 綜合多源結果，生成自然語言答案

---

## 二、開發狀態檢查清單

### ✅ 已完成部分
- [x] **項目骨架與配置**
  - 環境設定檔 (`skeleton/config.py`) 支援 Gemini & Ollama 雙引擎
  - Docker Compose 配置完整（PostgreSQL、Neo4j、pgAdmin、Ollama 服務）
  - 虛擬環境 & 依賴管理完備

- [x] **LLM 整合層**
  - 函數調用（Tool Use）機制實現完整
  - 支援 Gemini 原生工具調用 API 與 Ollama JSON 路由兩種模式
  - 登入狀態檢測與權限注入機制已實現

- [x] **Web UI 與對話框架**
  - Gradio 介面完整（聊天、登入、註冊、歷史記錄）
  - 認證流程骨架完成（待資料庫實現）
  - 結果顯示與規範化邏輯完整

- [x] **向量資料庫層**
  - `policy_documents` 表結構完整
  - pgvector 向量索引已設定
  - `query_policy_vector_search()` 函數已實現
  - 支援 Ollama (768-dim) 與 Gemini (3072-dim) 向量規格

- [x] **資料驅動層骨架**
  - PostgreSQL 與 Neo4j 連線驅動完成
  - 查詢工廠函數模板已建立
  - Mock 資料集完整（15+ JSON 檔案）

---

### 🟡 核心必備功能 (Must-have) — 期末作業基本要求

#### A. PostgreSQL 關係型資料層
- [ ] **Schema 設計與建立**
  - [ ] **核心表結構**（`databases/relational/schema.sql`）
    - `users` / `registered_users` — 用戶帳戶管理（主鍵：user_id）
    - `metro_stations` — 地鐵站點（主鍵：station_id）
    - `national_rail_stations` — 國鐵站點（主鍵：station_id）
    - `metro_schedules` — 地鐵班次（主鍵：schedule_id，外鍵：line_id）
    - `national_rail_schedules` — 國鐵班次（主鍵：schedule_id）
    - `national_rail_seat_layouts` — 車廂座位配置（主鍵：layout_id，外鍵：schedule_id）
    - `national_rail_bookings` — 訂單紀錄（主鍵：booking_id，外鍵：user_id, schedule_id）
    - `metro_travel_history` — 地鐵出行履歷（主鍵：trip_id）
    - `payments` — 付款紀錄（主鍵：payment_id）
  - [ ] **約束條件**
    - 外鍵完整性（schedule_id → schedules.schedule_id）
    - 唯一性約束（user_id, email）
    - NOT NULL 檢驗（關鍵欄位）
    - 檢查約束（票價 > 0、日期邏輯一致）

- [ ] **查詢函數實現**（`databases/relational/queries.py`）
  - [ ] `query_national_rail_availability(origin_id, destination_id, travel_date)`
    - 返回滿足路線的所有班次及座位狀態
    - 需檢查班次是否在指定日期營運
    - 邊界條件：無班次可用時返回空陣列
  - [ ] `query_national_rail_fare(origin_id, destination_id, fare_class)`
    - 查詢國鐵票價，支援 fare_class 篩選（standard, first, senior）
  - [ ] `query_metro_schedules(line_id, direction, travel_date)`
    - 查詢地鐵線路班次及時間表
  - [ ] `query_metro_fare(origin_id, destination_id)`
    - 地鐵區間票價計算（基於跨越站點數）
  - [ ] `query_available_seats(schedule_id, travel_date)`
    - 返回該班次座位可用狀態（coach + seat_id 組合）
  - [ ] `auto_select_adjacent_seats(schedule_id, travel_date, count)`
    - 智能座位自動分配（優先選擇相鄰座位）
  - [ ] `query_user_profile(user_id)` 與 `query_user_bookings(user_id)`
    - 用戶帳戶查詢與訂單歷史
  - [ ] `execute_booking(...)` 與 `execute_cancellation(...)`
    - 事務性寫操作，需支援 ROLLBACK

- [ ] **資料種子填充**（`skeleton/seed_postgres.py`）
  - [ ] 將 `train-mock-data/` 的 JSON 檔案映射到 SQL INSERT
  - [ ] 實現 ON CONFLICT DO NOTHING 冪等性
  - [ ] 驗證資料完整性（無孤立外鍵）

#### B. Neo4j 圖資料庫層
- [ ] **圖模型設計**（`skeleton/seed_neo4j.py` + Cypher）
  - [ ] **節點標籤**
    - `Station(id, name, network_type, line)` — 統合地鐵 & 國鐵站點
    - `Line(id, name, operator)` — 線路資訊
  - [ ] **關係類型**
    - `[CONNECTS_TO]` — 相鄰站點連接（properties: travel_time_min, line）
    - `[INTERCHANGE]` — 地鐵↔國鐵轉換點
    - `[SERVES]` — 線路服務站點
  - [ ] **拓樸完整性**
    - 地鐵四條線 (M1-M4) 網路拓樸
    - 國鐵兩條線 (NR1-NR2) 網路拓樸
    - 至少 8 個轉換點配置

- [ ] **路徑查詢函數實現**（`databases/graph/queries.py`）
  - [ ] `query_shortest_route(origin_id, destination_id, network="auto")`
    - 使用 APOC Dijkstra 最小化總旅行時間
    - 返回路線 JSON：[station1 → station2 → ...]，含預估時間
  - [ ] `query_cheapest_route(origin_id, destination_id)`
    - 基於票價的最便宜路線（可能涉及多線轉換）
  - [ ] `query_alternative_routes(origin_id, destination_id, avoid_station_id)`
    - 迴避指定站點的替代路線（模擬故障情景）
  - [ ] `query_interchange_path(origin_id, destination_id)`
    - 優先返回涉及轉換的路線（地鐵↔國鐵）
  - [ ] `query_delay_ripple(affected_station_id, hops=2)`
    - 查詢受故障站點影響的相鄰站點（BFS 遍歷）

- [ ] **圖資料種子填充**
  - [ ] 批量建立 Station 節點（20+ 站點）
  - [ ] 建立 CONNECTS_TO 關係（依 adjacency 配置）
  - [ ] 建立 INTERCHANGE 關係（8+ 轉換點）
  - [ ] 驗證圖連通性

#### C. 整合測試與系統驗證
- [ ] **Agent 工具鏈完整性**
  - [ ] 所有 `query_*` 函數都能被 agent.py 成功呼叫
  - [ ] 結果正規化為結構化文字
  - [ ] 無拋出的 NotImplementedError

- [ ] **使用者故事驗證**（基於 README 示例）
  - [ ] *"Are there any trains from Central Station (NR01) to Ferndale (NR07) today?"*
    - 預期：返回 3-5 個班次，含出發時間、票價、座位狀態
  - [ ] *"What's the quickest metro route from MS01 to MS09?"*
    - 預期：返回最短路線，含轉車點與預估時間
  - [ ] *"My train was delayed — what compensation?"*
    - 預期：檢索政策文件，返回延誤補償規則

- [ ] **基本安全檢驗**
  - [ ] SQL 注入防護（使用參數化查詢）
  - [ ] 認證檢查（auth-gated 工具驗證 user_id）
  - [ ] 資料驗證（日期格式、站點 ID 有效性）

---

### 🔥 進階優化項 (Should-have/Could-have) — 高分加分點

#### Phase 2: 完整性補強
- [ ] **邊界案例處理**
  - [ ] 無可用座位時的 fallback 提案（例：建議下一班）
  - [ ] 同日往返票 (return ticket) 邏輯實現
  - [ ] 跨日期班次查詢（支援未來 14 天）
  - [ ] 轉換點轉換時間考量（轉換間隔 ≥15 分鐘驗證）

- [ ] **進階查詢功能**
  - [ ] `query_round_trip_itinerary()` — 往返行程規劃
  - [ ] `query_daily_revenue_report()` — 按班次統計收入
  - [ ] `query_occupancy_forecast()` — 座位佔用率預測
  - [ ] `query_user_loyalty_metrics()` — 用戶忠誠度分析

- [ ] **資料品質與一致性**
  - [ ] 資料庫中無孤立訂單（所有 booking 的 user_id 皆存在）
  - [ ] 邏輯時間一致（departure_time < arrival_time）
  - [ ] 座位容量一致（已訂座位 ≤ 總座位數）

#### Phase 3: 卓越加分項 (Bonus)
- [ ] **架構卓越性**
  - [ ] 統一異常處理機制
    - 自訂 `TransitFlowException` 類別
    - 所有查詢函數都捕捉 DBError、產生可讀錯誤訊息
    - Agent 異常處理層統一格式化回復
  - [ ] SOLID 原則重構
    - 提取 `DatabaseService` 基類，實現 `PostgreSQLService`, `Neo4jService`
    - 依賴注入模式替換直接驅動調用
    - 為單元測試提供 mock 介面

- [ ] **效能優化亮點**
  - [ ] 查詢結果快取機制（@lru_cache 裝飾器，TTL=5 min）
  - [ ] Neo4j 查詢使用連線池（批量操作最多 10 個同時查詢）
  - [ ] PostgreSQL 查詢計劃分析（EXPLAIN ANALYZE 驗證索引使用）
  - [ ] 向量相似度搜尋的預熱快取（首次啟動預加載 top-50 政策文件）

- [ ] **UI/UX 交互加分**
  - [ ] 查詢過程視覺反饋（顯示"正在查詢班次..."進度指示）
  - [ ] 路線圖可視化（基於 Neo4j 結果繪製網路拓樸圖）
  - [ ] 歷史搜尋快速復用（記憶常見路線查詢）
  - [ ] 多語言支援骨架（支援中英文 UI）

- [ ] **可觀測性與監控**
  - [ ] 結構化日誌記錄
    - 查詢耗時追蹤（記錄每個工具的執行時間）
    - 異常棧軌跡捕捉（結構化 JSON 格式）
  - [ ] Prometheus 指標暴露
    - 查詢計數器（by tool & status）
    - 回應時間直方圖（P95、P99 延遲）
  - [ ] 健康檢查端點（`/healthz`）驗證三個資料庫連線

---

## 三、檔案結構對應表

| 檔案/目錄 | 責任 | 關聯 Must-have | 狀態 |
|-----------|------|---------------|------|
| `databases/relational/schema.sql` | PostgreSQL 表定義 | A.1 | ❌ 待設計 |
| `databases/relational/queries.py` | PostgreSQL 查詢函數 | A.2 | ❌ 完全 TODO |
| `skeleton/seed_postgres.py` | PostgreSQL 資料種子 | A.3 | 🟡 部分 |
| `databases/graph/` (含 seed.cypher) | Neo4j 模型 & Cypher | B.1-B.2 | ❌ 完全 TODO |
| `skeleton/seed_neo4j.py` | Neo4j 節點/關係建立 | B.3 | ❌ 完全 TODO |
| `skeleton/agent.py` | 工具路由邏輯 | C.1 | ✅ 完成 |
| `skeleton/ui.py` | Web 介面 & 認證 | C.2 | 🟡 部分 |
| `skeleton/config.py` | 環境配置 | - | ✅ 完成 |

---

## 四、高分評分標準預期

### 基礎及格線 (Pass: 60%)
- [x] PostgreSQL schema 設計正確（至少 8 張表，正規化到 3NF）
- [x] 關係型查詢函數 ≥ 7 個可運行
- [x] Neo4j 圖模型拓樸正確（≥ 20 節點，正確的轉換點）
- [x] Agent 能呼叫至少 3 個工具且返回有意義結果

### 良好水準 (Good: 75%)
- [x] 所有 Must-have 功能完整
- [x] 邊界案例處理（無座位、無班次時的 fallback）
- [x] 資料驗證與異常捕捉
- [x] 使用者故事測試通過 ≥ 2 個

### 優秀水準 (Excellent: 85%+)
- [x] 所有 Must-have + Should-have 功能完整
- [x] 統一異常處理與日誌機制
- [x] 查詢結果快取與效能優化
- [x] 所有 4 個使用者故事通過
- [x] 程式碼覆蓋測試（pytest 驗證核心函數）

### 傑出水準 (Outstanding: 95%+)
- [x] 完整的 Phase 3 卓越項目實現
- [x] SOLID 原則重構 + 依賴注入
- [x] UI 可視化亮點（路線圖展示）
- [x] 可觀測性層完整（結構化日誌 + Prometheus 指標）
- [x] 技術文檔齊備（架構設計文檔、API 使用指南）

