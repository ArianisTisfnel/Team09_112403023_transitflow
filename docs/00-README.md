# TransitFlow 實作指南 — 導覽索引

> 本目錄包含完整的實作分工指南，供組員依序完成所有功能模組。  
> 終極驗收標準：`pytest tests/ -v` 全部 PASS。

---

## 閱讀順序

```
01（任務說明）→ 03（整體藍圖）→ 依分工認領主軸 A 或主軸 B → Stage 3（基礎設施的優化）
```

---

## 文件目錄

### 前置文件

| 檔案 | 說明 |
|---|---|
| [01-initial_agent_prompt.md](01-initial_agent_prompt.md) | 初始任務說明：TransitFlow 完整需求規格與驗收標準 |
| [03-overall_implementation_plan.md](03-overall_implementation_plan.md) | 總體實作藍圖：架構圖、平行分工策略、依賴關係圖 |

---

### 主軸 A — 關聯式資料庫（PostgreSQL）

| 編號 | 檔案 | 核心函式 |
|---|---|---|
| 04 | [04-A-schema-core-tables.md](04-A-schema-core-tables.md) | `users`、`metro_stations`、`national_rail_stations`、`metro_station_adjacencies` DDL |
| 05 | [05-A-schema-transit-tables.md](05-A-schema-transit-tables.md) | `metro_schedules`、`national_rail_schedules`、`national_rail_seat_layouts`、`national_rail_bookings`、`metro_travel_history`、`payments`、索引、pgvector |
| 06 | [06-A-query-user-profile-bookings.md](06-A-query-user-profile-bookings.md) | `query_user_profile`、`query_user_bookings`、`query_payment_info` |
| 07 | [07-A-query-nr-availability.md](07-A-query-nr-availability.md) | `query_national_rail_availability`（單日 + 14 天視窗） |
| 08 | [08-A-query-nr-fare-metro-schedules.md](08-A-query-nr-fare-metro-schedules.md) | `query_national_rail_fare`（含快取）、`query_metro_schedules`（含 JSONB 營運日） |
| 09 | [09-A-query-metro-fare-seats.md](09-A-query-metro-fare-seats.md) | `query_metro_fare`（班次查詢 + 跳數分層計費）、`query_available_seats`（JSONB 解析）、`auto_select_adjacent_seats`（相鄰選位） |
| 10 | [10-A-execute-booking.md](10-A-execute-booking.md) | `execute_booking`（原子交易、自動選位、座位衝突偵測） |
| 11 | [11-A-execute-cancellation.md](11-A-execute-cancellation.md) | `execute_cancellation`（狀態機驗證、稽核軌跡） |
| 12 | [12-A-auth-functions.md](12-A-auth-functions.md) | `register_user`、`login_user`、`get_user_secret_question`、`verify_secret_answer`、`update_password` |

---

### 主軸 B — 圖形資料庫（Neo4j）

| 編號 | 檔案 | 核心函式 |
|---|---|---|
| 13 | [13-B-neo4j-seed-stations.md](13-B-neo4j-seed-stations.md) | `seed_metro_stations`、`seed_national_rail_stations`（`:Station` 節點種子） |
| 14 | [14-B-neo4j-seed-connections.md](14-B-neo4j-seed-connections.md) | `seed_metro_connections`、`seed_national_rail_connections`（`CONNECTS_TO` 關係種子） |
| 15 | [15-B-neo4j-seed-interchange.md](15-B-neo4j-seed-interchange.md) | `seed_interchange_connections`（`INTERCHANGE` 關係種子，雙向） |
| 16 | [16-B-query-shortest-route.md](16-B-query-shortest-route.md) | `query_shortest_route`（APOC Dijkstra）、`query_station_connections` |
| 17 | [17-B-query-alternative-routes.md](17-B-query-alternative-routes.md) | `query_alternative_routes`（allSimplePaths + 節點過濾） |
| 18 | [18-B-query-interchange-path.md](18-B-query-interchange-path.md) | `query_interchange_path`、`validate_interchange_feasibility` |
| 19 | [19-B-query-delay-ripple.md](19-B-query-delay-ripple.md) | `query_delay_ripple`（BFS 主次影響區分類） |
| 20 | [20-B-query-cheapest-route.md](20-B-query-cheapest-route.md) | `query_cheapest_route`（allSimplePaths + 跨模組票價計算） |

---

### 進階功能

| 編號 | 檔案 | 核心函式 |
|---|---|---|
| 21 | [21-adv-fallback-date-range.md](21-adv-fallback-date-range.md) | `query_alternative_schedules_fallback`（跨午夜時差計算）、`query_schedules_by_date_range` |
| 22 | [22-adv-round-trip-analytics.md](22-adv-round-trip-analytics.md) | `query_round_trip_itinerary`、`query_daily_revenue_report`、`query_occupancy_forecast`、`query_user_loyalty_metrics` |

---

### Stage 3 — 基礎設施層（skeleton/ 骨架實作）

| 編號 | 檔案 | 核心內容 |
|---|---|---|
| 23 | [23-stage3.1-exception-layer.md](23-stage3.1-exception-layer.md) | `TransitFlowException` + 四子類別 + `@error_handler` 裝飾器 |
| 24 | [24-stage3.2-solid-refactor.md](24-stage3.2-solid-refactor.md) | `DatabaseService` ABC 層次 + `TransitFlowAgent`（DI）重構 |
| 25 | [25-stage3.3-performance-boost.md](25-stage3.3-performance-boost.md) | `CacheManager`（LRU+TTL）+ `Neo4jConnectionPool` 單例 + `warmup_policy_cache` |
| 26 | [26-stage3.4-ui-observability.md](26-stage3.4-ui-observability.md) | `StructuredLogger` + Prometheus 指標 + `healthz()` + `chat()` 生成器 |

---

## 依賴關係快速參照

```
主軸 A：04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12
                                              ↑
進階：  21（依賴 07、08）
        22（依賴 07、09、10）

主軸 B：B.0（scaffold 清理 + stub）→ 13 → 14 → 15 → 16、17、18、19、20
         │                                               ↑
         │                          20 跨模組依賴主軸 A 的 query_national_rail_fare + query_metro_fare
         │
         └─ B.0 必做兩件事（詳見 Rule 8、Rule 9 及 16-B-query-shortest-route.md）：
            ① 刪除 databases/graph/queries.py scaffold 頂部的
              `from neo4j import GraphDatabase` 與 `def _driver():` 兩段代碼
            ② 在 databases/graph/ 建立最小化 connection_pool.py stub
              （stub 範本見 16-B-query-shortest-route.md，Stage 3.3 完成後由正式版覆蓋）

Stage 3：23 → 24 → 25 → 26
         ↑
         23（exceptions）是 24（database_service）的前置條件
         25（cache）整合到主軸 A 的 queries.py（query_national_rail_fare / query_metro_schedules）
         25（connection_pool）是主軸 B queries.py 的前置條件
```

---

## 重要開發守則

1. **禁止修改的三個原始檔案**：`skeleton/config.py`、`skeleton/llm_provider.py`、`skeleton/seed_vectors.py`
2. **Stage 1-2 實作目標**：`databases/relational/schema.sql`、`databases/relational/queries.py`、`databases/graph/queries.py`
3. **Stage 3 實作目標**：`skeleton/` 下 11 個骨架檔案 + `databases/graph/connection_pool.py`（詳見 23–26）
4. **寫入操作必須手動管理 `autocommit=False`**，讀取操作使用 `_connect()`（autocommit=True）
5. **Neo4j 種子資料使用 `MERGE`**，不使用 `CREATE`，確保冪等重入
6. **`ValidationException` 從 `skeleton/exceptions.py` import**，驗證失敗時 `raise` 而非 `return`
7. **`query_available_seats` 和 `execute_booking` 絕對不使用任何快取**（防止超賣）
8. **`databases/graph/queries.py` scaffold 清理（主軸 B 開始時立即執行）**：`main` 分支的 scaffold 頂部已有 `from neo4j import GraphDatabase` 和 `def _driver():` 工廠函式，**必須在實作任何圖形查詢函式之前將這兩段代碼完整刪除，並在同目錄建立最小化 `connection_pool.py` stub**（stub 範本見 `16-B-query-shortest-route.md`）。若這兩段代碼仍存在，`performance_boost` 靜態掃描測試將失敗，且報錯訊息不會指向此處（詳見 `25-stage3.3-performance-boost.md`）
9. **兩個 scaffold 檔案的起點說明**（避免「需從頭建立」的誤解）：
   - **`databases/relational/queries.py`**：`main` 分支已有 scaffold，包含 `_connect()` 輔助函式（`autocommit=True` 的唯讀連線）以及 `query_policy_vector_search()` 的完整實作（標注 `already implemented — do not modify`）。組員在此檔案上**新增**其餘函式即可，不需從空白檔案開始。
   - **`databases/graph/queries.py`**：`main` 分支已有 scaffold，包含 `from neo4j import GraphDatabase` 與 `def _driver():` 兩段代碼。**這兩段代碼必須在開始實作任何查詢函式之前刪除**（不可保留至 Stage 3.3 才處理），並以 `get_pool()` 模式取代（見規則 8 及 `16-B-query-shortest-route.md`）。同樣是在 scaffold 上**新增**查詢函式，不是空白起點。
