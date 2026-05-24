# 25 — Stage 3.3｜效能提升（CacheManager + 連線池 + 暖機）

> **前置條件**：`24-stage3.2-solid-refactor.md` 完成
> **後續任務**：`26-stage3.4-ui-observability.md`

---

## 任務目標

實作三個效能元件，並整合到現有查詢函式：
1. `skeleton/cache.py`：`CacheManager`（LRU + TTL）及三個模組層級快取實例
2. `databases/graph/connection_pool.py`：`Neo4jConnectionPool` 單例模式
3. `skeleton/vector_warmup.py`：`warmup_policy_cache()` 預載政策文件

同時，將 `query_national_rail_fare` 和 `query_metro_schedules` 整合快取，
確保 `query_available_seats` 和 `execute_booking` **絕對不使用任何快取**。

---

## 目標檔案

| 檔案 | 主要任務 |
|---|---|
| `skeleton/cache.py` | `CacheManager` 類別 + `fare_cache`、`schedule_cache`、`policy_cache` 實例 |
| `databases/graph/connection_pool.py` | `Neo4jConnectionPool` 類別 + `get_pool()` 工廠函式 |
| `skeleton/vector_warmup.py` | `warmup_policy_cache()` + `TOP_K_WARMUP = 50` |
| `databases/relational/queries.py` | 整合快取到 `query_national_rail_fare` 和 `query_metro_schedules` |

---

## 介面規格

### CacheManager（skeleton/cache.py）

```python
class CacheManager:
    def __init__(self, max_size: int, ttl_seconds: int):
        self._max_size = max_size
        self._ttl = ttl_seconds          # 測試會讀這個屬性
        # 使用 collections.OrderedDict 實作 LRU
        # 每個 entry 儲存 (value, expire_at: float)
        # 使用 threading.Lock 保護並發存取
    
    def get(self, key: str):             # 回傳 value 或 None（過期也回 None）
    def set(self, key: str, value):      # LRU 驅逐：超過 max_size 時移除最舊
    def clear(self):                     # 清空資料並重置計數器
    def stats(self) -> dict:             # {"hits": int, "misses": int, "size": int}
```

**LRU 行為**：
- `get(key)` 命中時，將該 key 移到 OrderedDict 尾端（最近使用）
- `set(key, value)` 時，如果已存在先移除再插入到尾端
- 超過 `max_size` 時，移除 OrderedDict 最頭端的 key（最久未使用）

**TTL 行為**：
- 存入時記錄 `expire_at = time.monotonic() + ttl_seconds`
- `get()` 時若 `time.monotonic() > expire_at` 則視為過期，回傳 `None`
- TTL=0 時，存入後立即過期

**模組層級快取實例**：
```python
fare_cache     = CacheManager(max_size=500,  ttl_seconds=300)
schedule_cache = CacheManager(max_size=200,  ttl_seconds=300)
policy_cache   = CacheManager(max_size=100,  ttl_seconds=3600)
```
（具體數值可調整，但 TTL 必須 > 0）

---

### Neo4jConnectionPool（databases/graph/connection_pool.py）

```python
from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_pool = None  # 模組層級單例，測試會 monkeypatch 這個變數來重置

class Neo4jConnectionPool:
    def __init__(self, uri: str, auth: tuple, max_pool_size: int = 10):
        self._driver = GraphDatabase.driver(
            uri,
            auth=auth,
            max_connection_pool_size=max_pool_size,
        )
    
    def __enter__(self):
        return self          # 回傳 pool 本身，不是 driver
    
    def __exit__(self, *args):
        pass                 # 不關閉 driver（連線池保持常駐）
    
    def session(self, **kwargs):
        return self._driver.session(**kwargs)

def get_pool() -> Neo4jConnectionPool:
    global _pool
    if _pool is None:
        _pool = Neo4jConnectionPool(
            uri=NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            max_pool_size=10,
        )
    return _pool
```

**關鍵行為**：
- `get_pool()` 兩次呼叫回傳同一個物件（單例）
- `__exit__` 不呼叫 `self._driver.close()`
- `GraphDatabase.driver(...)` 必須以 `max_connection_pool_size=10` 作為 keyword arg 呼叫
- `with get_pool() as pool:` 語法中，`pool` 是 `Neo4jConnectionPool` 實例

---

### warmup_policy_cache（skeleton/vector_warmup.py）

```python
import psycopg2
from psycopg2.extras import RealDictCursor
from skeleton.cache import policy_cache
from skeleton.config import PG_DSN

TOP_K_WARMUP = 50   # 測試會驗證這個常數等於 50，且 SQL 參數也是 50

def warmup_policy_cache() -> int:
    try:
        with psycopg2.connect(PG_DSN) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, title, category, content FROM policy_documents LIMIT %s",
                    (TOP_K_WARMUP,)
                )
                rows = cur.fetchall()
        
        for row in rows:
            policy_cache.set(f"policy:{row['id']}", row)
        
        print(f"已預載 {len(rows)} 筆政策文件至快取")
        return len(rows)
    
    except Exception:
        return 0
```

**關鍵行為**：
- 快取 key 格式必須是 `"policy:{id}"`（整數 id，例如 `"policy:3"`）
- 成功時印出包含數量和「政策文件」字樣的訊息（stdout）
- DB 失敗時不拋出例外，回傳 0

---

## 快取整合到查詢函式

### query_national_rail_fare 快取整合

```python
# 在 databases/relational/queries.py 中
from skeleton.cache import fare_cache

def query_national_rail_fare(schedule_id, fare_class, stops_travelled):
    cache_key = f"fare:{schedule_id}:{fare_class}:{stops_travelled}"
    cached = fare_cache.get(cache_key)
    if cached is not None:
        return cached
    
    # ... 原有 DB 查詢邏輯 ...
    result = ...  # DB 查詢結果
    
    if result is not None:             # 只快取有效結果，None 不快取
        fare_cache.set(cache_key, result)
    
    return result
```

**快取 key 格式**：`"fare:{schedule_id}:{fare_class}:{stops_travelled}"`

### query_metro_schedules 快取整合

```python
from skeleton.cache import schedule_cache

def query_metro_schedules(origin_id, destination_id):
    cache_key = f"metro_sched:{origin_id}:{destination_id}"
    
    cached = schedule_cache.get(cache_key)
    if cached is not None:
        return cached
    
    # ... 原有 DB 查詢邏輯 ...
    result = ...
    
    schedule_cache.set(cache_key, result)
    return result
```

**快取 key 格式**：`"metro_sched:{origin_id}:{destination_id}"`

### 絕對禁止快取的函式

`query_available_seats` 和 `execute_booking` 的原始碼中**不能出現**：
- `fare_cache`
- `schedule_cache`
- `policy_cache`
- 任何 `.get(` 或 `.set(` 呼叫快取物件的模式

**原因**：這兩個函式涉及即時座位狀態，快取會導致超賣（oversell）。

---

## databases/graph/queries.py 的要求

> ⚠️ **scaffold 殘留清理（必做，否則靜態掃描失敗）**：`main` 分支的 `databases/graph/queries.py` scaffold 在頂部有 `from neo4j import GraphDatabase` 以及 `def _driver():` 工廠函式。完成 Stage 1-2 查詢實作後，**這兩段代碼必須在本任務開始前刪除**。測試的靜態掃描不會指出是哪行導致失敗，請確認檔案中這兩者均不存在。

測試會靜態掃描 `databases/graph/queries.py` 的原始碼，確認：
1. 不含 `def _driver`（舊版工廠函式）
2. 含有 `get_pool`（使用新連線池）
3. 不含 `GraphDatabase`（不直接 import neo4j driver）

---

## 驗收標準

**CacheManager**：
1. miss 回傳 `None`，set 後 get 回正確值
2. TTL=0 立即過期
3. LRU 驅逐：`max_size=3`，`a/b/c` 存入後訪問 `a`，再存 `d`，`b` 被驅逐
4. `stats()` 正確回傳 `hits/misses/size`
5. `clear()` 清空資料並重置計數器
6. `_ttl` 屬性必須大於 0（fare_cache / schedule_cache / policy_cache）

**Neo4jConnectionPool**：
1. `get_pool()` 回傳 `Neo4jConnectionPool` 實例
2. 兩次呼叫 `get_pool()` 回傳同一物件
3. `GraphDatabase.driver` 使用 `max_connection_pool_size=10`
4. `__enter__` 回傳 pool 本身
5. `__exit__` 不呼叫 `driver.close()`
6. `pool.session(database="neo4j")` 委派給 `driver.session(database="neo4j")`

**warmup_policy_cache**：
1. 成功時回傳載入文件數
2. 快取 key 為 `"policy:{id}"`
3. 輸出包含數量和「政策文件」字樣
4. DB 失敗回傳 0，不拋出例外
5. `TOP_K_WARMUP == 50`，SQL 參數也是 `(50,)`

**快取整合**：
1. `query_national_rail_fare` 第二次相同呼叫不觸及 DB
2. `query_metro_schedules` 第二次相同呼叫不觸及 DB
3. `fare_cache.get("fare:NR_SCH01:senior:1")` 在呼叫後非 `None`（key 格式 `fare:{schedule_id}:{fare_class}:{stops_travelled}`）
4. `schedule_cache.get("metro_sched:MS01:MS10")` 在呼叫後非 `None`（key 格式 `metro_sched:{origin_id}:{destination_id}`）
5. `query_available_seats` 原始碼不含任何快取變數名稱
6. `execute_booking` 原始碼不含任何快取變數名稱

**執行測試**：
```bash
pytest tests/unit/ -v -k "performance_boost"
```
