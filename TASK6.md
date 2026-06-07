# Task 6 — Optional Extension

本組的延伸分兩層，所有延伸程式碼皆以 `# TASK 6 EXTENSION:` 註解標記：

- **§A 主要延伸 — Database Access Performance Layer**：在既有查詢之上加入 **TTL-aware
  LRU 查詢快取** 與 **Neo4j 連線池**，直接觸及資料庫核心存取邏輯。
- **§B 次要延伸 — Stage 3 Robustness Layer**：例外體系、依賴注入的資料庫服務層、結構化
  日誌、Prometheus 指標、健康檢查、串流 UI，提升整體穩定性與可觀測性。

完整說明（動機、程式片段、範例輸出、測試佐證）見設計文件
[`Team09_DESIGN_DOC.md`](Team09_DESIGN_DOC.md) Section 7。

---

## §A — Database Access Performance Layer（主要延伸）

> 一句話：在既有資料庫查詢之上加一層**讀取快取**與**連線池**，讓 agent 對低變動資料
> （票價、捷運班次、政策文件）的重複查詢**跳過資料庫往返**，並讓 Neo4j 改用單一連線池而非
> 每次查詢新建 driver。**座位與訂票絕不快取**（避免超賣），由測試強制保證。

### 新增檔案

| 檔案 | 內容 | 主要 function / 物件 |
|---|---|---|
| `skeleton/cache.py` | thread-safe LRU + per-entry TTL 快取 | `CacheManager`（`get`/`set`/`clear`/`stats`）；module 實例 `fare_cache`、`schedule_cache`、`policy_cache` |
| `databases/graph/connection_pool.py` | Neo4j driver 單例（`max_connection_pool_size=10`） | `Neo4jConnectionPool`、`get_pool()` |
| `skeleton/vector_warmup.py` | 啟動時預載政策文件進 `policy_cache` | `warmup_policy_cache()`、`TOP_K_WARMUP=50` |

### 修改檔案

| 檔案 | 修改內容 | 受影響函式 / cache key |
|---|---|---|
| `databases/relational/queries.py` | 票價／班次查詢加入「先查快取、命中跳過 DB、miss 不快取」 | `query_national_rail_fare`（key `fare:{schedule_id}:{fare_class}:{stops_travelled}`）、`query_metro_schedules`（key `metro_sched:{origin_id}:{destination_id}`） |
| `databases/graph/queries.py` | 6 個查詢改用 `with get_pool() as driver:`，移除 per-query driver 工廠 | `query_shortest_route`、`query_interchange_path`、`query_station_connections`、`query_delay_ripple` 等 |

### 受影響的資料表 / 資料來源

| 資料庫 | 資料表 | 在延伸中的角色 |
|---|---|---|
| PostgreSQL | `national_rail_schedules` | 票價查詢來源 → 結果進 `fare_cache` |
| PostgreSQL | `metro_schedules` | 班次查詢來源 → 結果進 `schedule_cache` |
| PostgreSQL + pgvector | `policy_documents` | 啟動時前 50 筆預載進 `policy_cache` |
| Neo4j | `:MetroStation` / `:NationalRailStation` 節點 / `METRO_LINK`、`RAIL_LINK`、`INTERCHANGE_TO` 關係 | 透過 `get_pool()` 共用連線池查詢 |

### 安全邊界（不快取，避免超賣）

下列函式經測試斷言**原始碼不得出現任何 cache 物件**：

- `query_available_seats`（即時座位）
- `execute_booking`（交易型寫入）

### 測試佐證

```
$ pytest tests/unit/test_phase_3.3_performance_boost.py -q
51 passed in 0.30s
```

涵蓋：`CacheManager` TTL/LRU、module 實例、`Neo4jConnectionPool` 單例與池大小、
`warmup_policy_cache`、票價/班次快取整合（命中跳過 DB）、不快取約束、圖查詢改用連線池。

### 如何驗證

```python
from databases.relational.queries import query_national_rail_fare
from skeleton.cache import fare_cache

query_national_rail_fare("NR_SCH01", "standard", 5)   # 第一次：查 DB
query_national_rail_fare("NR_SCH01", "standard", 5)   # 第二次：命中快取
print(fare_cache.stats())     # → hits=1，第二次未打 DB
```

---

## §B — Stage 3 Robustness Layer（次要延伸）

> 在資料庫核心邏輯之外，補上一層生產級的穩定性與可觀測性設施。這些不直接改動資料庫綱要或
> 查詢結果，但讓資料庫存取**失敗時不外洩 traceback、可監控、可健檢、可注入替身測試**。

### 新增檔案

| 檔案 | 內容 | 主要 function / 物件 |
|---|---|---|
| `skeleton/exceptions.py` | 領域例外體系，配合 `@error_handler` 把失敗轉成結構化 JSON | `TransitFlowException` 及其子類、`.error_code` |
| `skeleton/database_service.py` | 依賴注入：抽象資料庫存取介面，agent 不再直接耦合驅動 | `DatabaseService`、`RelationalService`/`PostgreSQLService`、`GraphService`/`Neo4jService` |
| `skeleton/logging_config.py` | 每行一筆 JSON 的結構化日誌 | `StructuredLogger` |
| `skeleton/metrics.py` | Prometheus 計數器/直方圖 | `query_counter`、`query_duration` |
| `skeleton/health_check.py` | 探測兩個資料庫連線健康 | `healthz()` |

### 修改檔案

| 檔案 | 修改內容 | 受影響項目 |
|---|---|---|
| `skeleton/agent.py` | 改為注入 `DatabaseService`，工具呼叫包 `@error_handler` + 指標/日誌 | `TransitFlowAgent`、`@error_handler` |
| `skeleton/ui.py` | 串流式聊天輸出 + 工具執行即時狀態提示 | generator-based `chat()` |

### 測試佐證

```
$ pytest tests/unit/test_phase_3.1_exception_layer.py \
         tests/unit/test_phase_3.2_solid_refactor.py \
         tests/unit/test_phase_3.4_ui_observability.py -q
```

涵蓋例外轉換、DI 服務替身、結構化日誌欄位、指標標籤、健康檢查回傳格式。

### 說明

§B 為依早期規劃（老師更新前的 README.md 中提到的加分項）所建的健壯性層；其價值在於**讓資料庫存取在真實故障情境下安全降級**
（例外→結構化錯誤、連線→可健檢、查詢→可監控），與 §A 的效能層互補。

---

## §C — pgvector 工具路由器（主要延伸，DB 驅動）

> 一句話：用 **pgvector 對「使用者問題 ↔ 工具描述」做餘弦相似度**，當小模型
> （`llama3.2:1b`）漏選工具時，以最相關的工具作為候選/後備，修正錯誤路由。
> 旗標 `USE_EMBEDDING_ROUTER` 預設 **OFF**，既有行為與測試完全不變。

### 新增檔案

| 檔案 | 內容 | 主要 function / 物件 |
|---|---|---|
| `skeleton/seed_tool_router.py` | 把 12 個工具描述嵌入 `tool_descriptions`（冪等；排除與 `get_metro_fare` 重複的 `calculate_metro_fare`） | `seed()`、`TRIGGER_PHRASES`、`SKIP_TOOLS` |
| `eval/tool_routing_eval.py` + `eval/routing_testset.json` | 離線量測路由準確率（18 題） | top-1 / recall@k |
| `tests/unit/test_tool_router.py` | 路由器單元測試（10 項，mock，無需 DB） | — |

### 修改檔案

| 檔案 | 修改內容 | 受影響項目 |
|---|---|---|
| `databases/relational/schema.sql` | 新增 `tool_descriptions(name PK, description, trigger_phrases, embedding vector(768))` + HNSW 索引 | `-- TASK 6 EXTENSION (§C)` |
| `databases/relational/queries.py` | 新增相似度查詢與 upsert | `query_tool_candidates()`、`store_tool_description()` |
| `skeleton/database_service.py` | `PostgreSQLService` 加 `query_tool_candidates`（維持 DI，agent 不直接 import 查詢） | `PostgreSQLService.query_tool_candidates` |
| `skeleton/agent.py` | 旗標控制的後備路由（LLM/規則皆未選時用相似度候選 + best-effort 參數）；另加 `search_policy` 小模型參數救援（缺 `query` 時以使用者訊息回填，避免崩潰） | `_embedding_route_candidates()`、`_router_params_for()` |
| `skeleton/config.py` | 旗標與門檻 | `USE_EMBEDDING_ROUTER`、`TOOL_ROUTER_TOP_K`、`TOOL_ROUTER_THRESHOLD` |

### 受影響的資料表 / 資料來源

| 資料庫 | 資料表 | 角色 |
|---|---|---|
| PostgreSQL + pgvector | `tool_descriptions` | 工具描述向量；`query_tool_candidates` 以餘弦相似度排序 |

### 測試佐證

```
$ pytest tests/unit/test_tool_router.py -q          # 10 passed
$ python eval/tool_routing_eval.py                  # 18 題：top-1 89%、recall@4 100%
```

> 補強記錄：排除與 `get_metro_fare` 重複的 `calculate_metro_fare`、強化易混工具的
> trigger 字眼後，top-1 由 72% → **89%**、recall@4 由 94% → **100%**。

before/after（旗標 OFF→ON，問題：「Can I get a refund if my train is delayed 45 minutes?」）：
- **OFF**：`llama3.2:1b` 未呼叫 `search_policy`，回「需先登入」（錯誤幻覺）。
- **ON**：路由器命中 `search_policy` → 正確引用 Delay Compensation 政策（誤點 <59 分退 50%）。

完整動機／schema／範例查詢與輸出見 [`Team09_DESIGN_DOC.md`](Team09_DESIGN_DOC.md) §7.6。
