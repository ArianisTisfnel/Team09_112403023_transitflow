# 24 — Stage 3.2｜SOLID 資料庫服務層（Dependency Injection）

> **前置條件**：`23-stage3.1-exception-layer.md` 完成（`TransitFlowException` 層次已定義）
> **後續任務**：`25-stage3.3-performance-boost.md`

---

## 任務目標

在 `skeleton/database_service.py` 中建立完整的 ABC 服務層，並重構 `skeleton/agent.py`
使其以依賴注入（DI）方式接收服務物件，不再直接 import psycopg2、neo4j 或任何查詢模組。

**目標檔案**：
- `skeleton/database_service.py`（ABC 層次 + 兩個具體實作類別）
- `skeleton/agent.py`（重構為 `TransitFlowAgent` 類別，保留向後相容介面）

---

## 介面規格

### skeleton/database_service.py — ABC 層次

```
DatabaseService(ABC)                    ← 所有服務的根基類別
├── RelationalService(DatabaseService)  ← 關聯式資料庫抽象（含抽象方法）
│   └── PostgreSQLService(dsn)         ← 具體實作，委派給 databases.relational.queries
└── GraphService(DatabaseService)       ← 圖形資料庫抽象（含抽象方法）
    └── Neo4jService(uri)              ← 具體實作，委派給 databases.graph.queries
```

#### RelationalService（抽象類別）

抽象方法（至少需宣告）：
```python
@abstractmethod
def query_national_rail_availability(self, origin_id, destination_id, travel_date=None): ...
@abstractmethod
def query_national_rail_fare(self, origin_id, destination_id, fare_class="standard"): ...
@abstractmethod
def query_metro_schedules(self, origin_id, destination_id): ...
@abstractmethod
def query_metro_fare(self, origin_id, destination_id): ...
@abstractmethod
def query_available_seats(self, schedule_id, travel_date, fare_class): ...
@abstractmethod
def auto_select_adjacent_seats(self, *args, **kwargs): ...
@abstractmethod
def query_user_profile(self, email): ...
@abstractmethod
def query_user_bookings(self, *args, **kwargs): ...
@abstractmethod
def execute_booking(self, *args, **kwargs): ...
@abstractmethod
def execute_cancellation(self, booking_id, user_id): ...
@abstractmethod
def query_policy_vector_search(self, embedding): ...
```

#### PostgreSQLService（具體類別）

```python
class PostgreSQLService(RelationalService):
    def __init__(self, dsn: str):
        self.dsn = dsn
        import databases.relational.queries as _q
        self._q = _q
    
    def query_national_rail_availability(self, origin_id, destination_id, travel_date=None):
        return self._q.query_national_rail_availability(origin_id, destination_id, travel_date)
    
    def query_metro_schedules(self, origin_id, destination_id):
        return self._q.query_metro_schedules(origin_id, destination_id)
    
    def auto_select_adjacent_seats(self, *args, **kwargs):
        return self._q.auto_select_adjacent_seats(*args, **kwargs)
    
    # 所有其他抽象方法同樣委派給 self._q.*
```

**委派規則**：每個方法都直接呼叫 `self._q.<同名函式>(*args, **kwargs)`，不加額外邏輯。

特別注意測試期望的呼叫簽名：
- `svc.query_national_rail_availability("NR01", "NR05")` → `self._q.query_national_rail_availability("NR01", "NR05", None)`（補 None）
- `svc.query_metro_schedules("MS01", "MS09")` → `self._q.query_metro_schedules("MS01", "MS09")`（位置參數直接透傳）
- `svc.query_shortest_route("NR01", "NR05")` → `self._q.query_shortest_route("NR01", "NR05", "auto")`（補預設值）

> ⚠️ **`query_metro_schedules` 參數命名說明**：`RelationalService` 抽象方法使用 `(origin_id, destination_id)`，與 `databases/relational/queries.py` 中同名函式的實際參數名稱 `(line_id, direction, travel_date)` 不同。`PostgreSQLService.query_metro_schedules` 採用**位置參數直接透傳**（如上偽代碼），不做額外映射——`solid_refactor` 系列單元測試以 mock 驗證委派行為，不執行真實 DB 查詢，因此兩者在測試層面不衝突。

> ⚠️ **`query_metro_fare` 參數命名說明**：`RelationalService` 抽象方法使用 `(origin_id, destination_id)`，對應 `databases/relational/queries.py` 中的實際簽名 `query_metro_fare(origin_id: str, destination_id: str)`，兩者一致，直接委派即可。`PostgreSQLService.query_metro_fare` 偽代碼：`return self._q.query_metro_fare(origin_id, destination_id)`。

> ℹ️ **`auto_select_adjacent_seats` 說明**：此抽象方法為服務介面完整性而宣告（測試驗證子類別可被正常實例化）。函式簽名為 `auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]`，接收 `query_available_seats()` 的輸出並回傳 `count` 個盡量同排的 `seat_id` 字串 list（詳細規格與偽代碼見 `09-A-query-metro-fare-seats.md` 函式三）。`PostgreSQLService` 委派偽代碼：`return self._q.auto_select_adjacent_seats(*args, **kwargs)`。

> ℹ️ **`query_policy_vector_search` 說明（無需實作）**：`main` 分支的 `databases/relational/queries.py` scaffold 已包含此函式的完整實作，scaffold 文件字串也明確標注「already implemented — do not modify」。**請確認此函式存在即可，不需要也不應該重新實作或覆蓋它。**
>
> **`PostgreSQLService` 委派**：`return self._q.query_policy_vector_search(embedding)`（位置參數透傳，對應 scaffold 的現有實作）

#### GraphService（抽象類別）

抽象方法：
```python
@abstractmethod
def query_shortest_route(self, origin_id, destination_id, network="auto"): ...
@abstractmethod
def query_cheapest_route(self, origin_id, destination_id, network="auto"): ...
@abstractmethod
def query_alternative_routes(self, origin_id, destination_id, avoid_station_id, network="auto"): ...
@abstractmethod
def query_interchange_path(self, metro_station_id, rail_station_id): ...
@abstractmethod
def query_delay_ripple(self, delayed_station_id, hops=2): ...
```

#### Neo4jService（具體類別）

```python
class Neo4jService(GraphService):
    def __init__(self, uri: str):
        self.uri = uri
        import databases.graph.queries as _q
        self._q = _q
    
    def query_shortest_route(self, origin_id, destination_id, network="auto"):
        return self._q.query_shortest_route(origin_id, destination_id, network)
    
    # 其餘方法同樣委派，帶預設值
```

---

### skeleton/agent.py — TransitFlowAgent 類別

```python
class TransitFlowAgent:
    def __init__(self, db_service: RelationalService, graph_service: GraphService):
        self.db = db_service
        self.graph = graph_service
    
    @error_handler
    def _execute_tool(self, tool_name: str, params: dict) -> str:
        # 所有工具派遣邏輯，透過 self.db.* 和 self.graph.*
        ...
    
    def run(self, message: str, history: list, stream: bool = False,
            progress_callback=None, session_id=None) -> tuple[str, list]:
        # LLM tool-calling 迴圈
        ...
```

**模組層級向後相容介面**：
```python
from skeleton.config import PG_DSN, NEO4J_URI   # 從 config 模組取得連線字串

# 模組層級預設實例
_default_agent = TransitFlowAgent(
    db_service=PostgreSQLService(dsn=PG_DSN),
    graph_service=Neo4jService(uri=NEO4J_URI),
)

def run_agent(message, history, stream=False, progress_callback=None, session_id=None):
    return _default_agent.run(message, history, stream, progress_callback, session_id)
```

**絕對禁止**（測試會做原始碼掃描）：
- `import psycopg2`
- `from psycopg2 import ...`
- `import neo4j`
- `from neo4j import ...`
- `from databases.relational.queries import ...`
- `from databases.graph.queries import ...`

---

## _execute_tool 工具派遣對應表

| 工具名稱 | 呼叫目標 | 說明 |
|---|---|---|
| `check_national_rail_availability` | `self.db.query_national_rail_availability(...)` | 傳入 `origin_id`, `destination_id`，可選 `travel_date` |
| `check_metro_availability` | `self.db.query_metro_schedules(origin_id=..., destination_id=...)` | 注意使用 keyword args |
| `get_available_seats` | `self.db.query_available_seats(schedule_id=..., travel_date=..., fare_class=...)` | keyword args |
| `find_route`（跨網路：MS→NR 或 NR→MS） | `self.graph.query_interchange_path(origin_id, destination_id)` | **優先權最高**，在判斷 `optimise_by` 之前先執行跨網路偵測 |
| `find_route`（`optimise_by="cost"`，同網路） | `self.graph.query_cheapest_route(origin_id=..., destination_id=..., network=...)` | 票價最低；僅在非跨網路時適用 |
| `find_route`（`optimise_by="time"` 或預設，同網路） | `self.graph.query_shortest_route(origin_id=..., destination_id=..., network=...)` | 時間最短；僅在非跨網路時適用 |
| `find_alternative_routes` | `self.graph.query_alternative_routes(origin_id=..., destination_id=..., avoid_station_id=..., network=...)` | keyword args |
| `get_delay_ripple` | `self.graph.query_delay_ripple(delayed_station_id=..., hops=2)` | keyword args |
| `search_policy` | `self.db.query_policy_vector_search(embedding)` | 需先用 LLM embed query |
| `make_booking` | `self.db.execute_booking(user_id=..., schedule_id=..., origin_station_id=..., destination_station_id=..., travel_date=..., fare_class=..., seat_id=..., ticket_type=...)` | 完整透傳 params 所有欄位；`seat_id` 若缺失則預設 `"any"` |
| `cancel_booking` | `self.db.execute_cancellation(booking_id=..., reason=params.get("reason", "Customer requested"))` | `reason` 有預設值，可選 |
| `get_user_profile` | `self.db.query_user_profile(user_id=...)` | 從 params 取 `user_id` |
| `get_user_bookings` | `self.db.query_user_bookings(user_id=...)` | 從 params 取 `user_id` |

### find_route 分支偽代碼（偵測順序）

`find_route` 的三個分支有**明確的優先順序**，必須按以下順序判斷（先跨網路、再 optimise_by）：

```
origin_id      = params["origin_id"]
destination_id = params["destination_id"]
network        = params.get("network", "auto")
optimise_by    = params.get("optimise_by", "time")

# 1. 跨網路偵測（優先權最高）
#    判斷準則：一端以 "MS"（捷運）開頭、另一端以 "NR"（國鐵）開頭
#    使用 .upper().startswith() 以忽略大小寫

is_cross = (
    (origin_id.upper().startswith("MS") and destination_id.upper().startswith("NR"))
    or
    (origin_id.upper().startswith("NR") and destination_id.upper().startswith("MS"))
)

if is_cross:
    # 跨網路一律走換乘路徑，不管 optimise_by 是什麼
    result = self.graph.query_interchange_path(origin_id, destination_id)

elif optimise_by == "cost":
    # 同網路、票價最低
    result = self.graph.query_cheapest_route(
        origin_id=origin_id, destination_id=destination_id, network=network
    )

else:
    # 同網路、時間最短（預設）
    result = self.graph.query_shortest_route(
        origin_id=origin_id, destination_id=destination_id, network=network
    )
```

> ⚠️ **常見錯誤**：若先判斷 `optimise_by == "cost"` 再判斷 `is_cross`，
> 跨網路 + `optimise_by="cost"` 的查詢會誤呼叫 `query_cheapest_route`，
> 導致 interchange 相關測試失敗，且報錯訊息只顯示結果欄位不符，不會指向路由邏輯。

---

## run() 實作導引

`run()` 是 LLM tool-calling 迴圈的主體，負責把自然語言輸入轉成工具呼叫序列，最後彙整成自然語言回答。
`main` 分支的 `skeleton/agent.py` 已有一版可運作的 `run()` 邏輯；DI 重構只需要兩件事：
1. 把所有直接呼叫 `queries.xxx()` 的地方換成 `self._execute_tool(tool_name, params)`
2. 在每次執行工具前呼叫 `progress_callback`

```
偽代碼：

def run(self, message, history, stream=False, progress_callback=None, session_id=None):
    # 步驟一：建立初始訊息列表（含系統角色 + 歷史對話 + 本輪使用者輸入）
    messages = build_messages(history, message)   # 參考 main 分支已有的實作
    tool_calls_log = []
    
    # 步驟二：LLM tool-calling 迴圈
    while True:
        response = llm_provider.call_with_tools(messages, tools=TOOL_DEFINITIONS)
        
        if response has tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.name
                params    = tool_call.arguments   # dict
                
                # ← 通知 UI 進度（在執行工具之前觸發，非之後）
                if progress_callback is not None:
                    progress_callback(tool_name)
                
                # ← 透過 DI 執行工具（不直接呼叫 queries.py）
                result = self._execute_tool(tool_name, params)
                tool_calls_log.append(tool_name)
                
                # 把工具回傳加入對話，讓 LLM 繼續推理
                messages.append(tool_result_message(tool_call.id, result))
        
        else:
            # LLM 不再呼叫工具，回傳最終自然語言答案
            final_answer = response.text
            break
    
    return final_answer, tool_calls_log
```

**實作注意事項**：
- `llm_provider.call_with_tools`、`build_messages`、`TOOL_DEFINITIONS` 的具體 API 來自 `skeleton/llm_provider.py`；直接沿用 `main` 分支 `agent.py` 中的呼叫方式，不需重新設計。
- `progress_callback` 必須在工具**執行前**觸發，而非執行後（UI 顯示「正在處理...」的時機）。
- 若某輪 LLM 回應沒有任何工具呼叫，`progress_callback` 不被呼叫（`tool_calls_log` 為空）。
- `_execute_tool` 已套上 `@error_handler`，永遠回傳字串，不會拋出例外，可安全加入 messages。

---

## 驗收標準

**測試驗證的關鍵行為**：

ABC 層次：
1. `DatabaseService` 繼承自 `ABC`
2. `RelationalService()` 和 `GraphService()` 直接實例化時拋出 `TypeError`
3. `RelationalService` 和 `GraphService` 都繼承自 `DatabaseService`
4. `PostgreSQLService` 繼承自 `RelationalService`（遞移繼承自 `DatabaseService`）
5. `Neo4jService` 繼承自 `GraphService`（遞移繼承自 `DatabaseService`）

PostgreSQLService / Neo4jService：
1. `PostgreSQLService(dsn="...")` 可正常建立，`.dsn` 屬性正確
2. `Neo4jService(uri="...")` 可正常建立，`.uri` 屬性正確
3. 每個方法呼叫都委派給 `self._q.<同名函式>`

TransitFlowAgent DI：
1. `__init__` 接受 `db_service` 和 `graph_service`，分別儲存為 `self.db` 和 `self.graph`
2. `_execute_tool` 透過注入的服務呼叫，不直接碰 DB
3. `_execute_tool.__wrapped__` 存在（`@error_handler` 保持有效）

原始碼耦合檢查（靜態掃描）：
1. `skeleton/agent.py` 不含 `import psycopg2`
2. `skeleton/agent.py` 不含 `from neo4j`
3. `skeleton/agent.py` 不含 `from databases.relational.queries import`
4. `skeleton/agent.py` 不含 `from databases.graph.queries import`

向後相容：
1. `run_agent` 函式可呼叫
2. `_default_agent` 是 `TransitFlowAgent` 的實例
3. `_default_agent.db` 是 `PostgreSQLService` 的實例
4. `_default_agent.graph` 是 `Neo4jService` 的實例
5. `run_agent("hello", [])` 委派給 `_default_agent.run("hello", [], False, None, None)`

**執行測試**：
```bash
pytest tests/unit/ -v -k "solid_refactor"
```
