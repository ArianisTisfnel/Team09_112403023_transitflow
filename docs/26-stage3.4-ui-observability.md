# 26 — Stage 3.4｜UI 可觀察性（StructuredLogger + Prometheus + UI 生成器）

> **前置條件**：`25-stage3.3-performance-boost.md` 完成
> **後續任務**：無（本任務為 Stage 3 最終 Micro-task）

---

## 任務目標

實作四個可觀察性基礎設施元件，並整合到 agent 和 UI 層：
1. `skeleton/logging_config.py`：`StructuredLogger`（每次呼叫輸出一行 JSON 到 stderr）
2. `skeleton/metrics.py`：Prometheus `query_counter`（Counter）和 `query_duration`（Histogram）
3. `skeleton/health_check.py`：`healthz()` 回傳 JSON 健康報告
4. `skeleton/maintenance_check.py`：三項資料完整性自我檢查
5. `skeleton/agent.py` 更新：整合 logger、計時、Prometheus、`progress_callback`
6. `skeleton/ui.py` 更新：`chat()` 改為生成器函式、加入 `_TOOL_STATUS` 字典

---

## 介面規格

### skeleton/logging_config.py — StructuredLogger

```python
import json
import logging
import traceback
from datetime import datetime, timezone

class StructuredLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        
        handler = logging.StreamHandler()  # 輸出到 stderr
        handler.setFormatter(logging.Formatter("%(message)s"))
        if not self._logger.handlers:
            self._logger.addHandler(handler)
    
    def _emit(self, level: str, event: str, exc=None, **kwargs):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **kwargs,
        }
        if exc is not None:
            record["stack_trace"] = traceback.format_exc()
        
        getattr(self._logger, level)(json.dumps(record))
    
    def info(self,    event: str, **kwargs): self._emit("info",    event, **kwargs)
    def warning(self, event: str, **kwargs): self._emit("warning", event, **kwargs)
    def error(self,   event: str, exc=None, **kwargs): self._emit("error", event, exc=exc, **kwargs)
    def debug(self,   event: str, **kwargs): self._emit("debug",   event, **kwargs)
```

**關鍵規格**：
- `timestamp` 欄位必須是 ISO 8601 格式（`datetime.fromisoformat()` 可解析）
- `event` 欄位的值等於傳入的 `event` 參數
- 額外的 `**kwargs` 直接展開到 JSON 物件頂層（例如 `tool="find_route"` → `{"tool": "find_route", ...}`）
- `error()` 傳入 `exc=` 時，加入 `"stack_trace"` 欄位（`traceback.format_exc()` 結果）
- `error()` 沒有 `exc=` 時，**不加** `"stack_trace"` 欄位
- 每次呼叫輸出**恰好一行** JSON（不多不少）
- `stack_trace` 是合法的 JSON 字串（含換行但整體是 JSON 字串型態）

---

### skeleton/metrics.py — Prometheus 指標

```python
from prometheus_client import Counter, Histogram

query_counter = Counter(
    "transitflow_query_total",
    "Total number of tool queries",
    ["tool", "status"],         # 標籤：tool 和 status
)

query_duration = Histogram(
    "transitflow_query_duration_seconds",
    "Tool query duration in seconds",
    ["tool"],                   # 標籤：只有 tool
)
```

**關鍵規格**：
- `query_counter` 是 `prometheus_client.Counter` 的實例
- `query_duration` 是 `prometheus_client.Histogram` 的實例
- `query_counter._labelnames` 包含 `"tool"` 和 `"status"`
- `query_duration._labelnames` 包含 `"tool"`
- `query_counter.labels(tool="find_route", status="success").inc()` 可正常執行
- `query_duration.labels(tool="search_policy").observe(0.123)` 可正常執行

---

### skeleton/health_check.py — healthz()

```python
import json
import psycopg2
import neo4j
from skeleton.config import PG_DSN, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

def healthz() -> str:
    pg_status = "healthy"
    n4j_status = "healthy"
    
    try:
        psycopg2.connect(PG_DSN)
    except Exception as e:
        pg_status = f"unhealthy: {e}"
    
    try:
        neo4j.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception as e:
        n4j_status = f"unhealthy: {e}"
    
    all_healthy = (pg_status == "healthy" and n4j_status == "healthy")
    
    return json.dumps({
        "status": "healthy" if all_healthy else "degraded",
        "databases": {
            "postgresql": pg_status,
            "neo4j": n4j_status,
        }
    })
```

**關鍵規格**：
- 回傳值是字串（`json.dumps` 的結果）
- 有 `"status"` 和 `"databases"` 兩個頂層 key
- `"databases"` 有 `"postgresql"` 和 `"neo4j"` 兩個 key
- 兩者都正常時 `"status": "healthy"`，任一失敗時 `"status": "degraded"`
- 失敗時對應 DB 的值包含 `"unhealthy"` 字樣，且包含原始例外訊息
- `healthz()` **永遠不拋出例外**（try/except 全包住）

---

### skeleton/maintenance_check.py — 三項資料完整性自我檢查

**目標檔案**：`skeleton/maintenance_check.py`（新建）

**匯出的五個函式**：

```python
from skeleton.maintenance_check import (
    check_orphan_bookings,
    check_schedule_time_logic,
    check_capacity_consistency,
    run_checks,
    apply_repairs,
)
```

#### 共用子檢查回傳結構

每個 `check_*` 函式接收一個已開啟的游標 `cur`，執行查詢後回傳：

```python
{
    "check":       "check_name",       # 固定字串識別碼，見各函式
    "description": "...",              # 一句話描述本項檢查目的
    "status":      "PASS" | "FAIL",    # 有任何違規即 FAIL
    "count":       int,                # 違規筆數（0 → PASS）
    "records":     [dict, ...],        # 違規記錄（必須 JSON 可序列化）
    "repair_sql":  [str, ...]          # 修復用 SQL 字串（每筆問題一條）
}
```

**序列化規則**：`records` 中的 `date`、`time`、`datetime` 物件必須呼叫 `.isoformat()` 轉為字串，確保整份報告可直接 `json.dumps()` 序列化。

---

#### check_orphan_bookings(cur) → dict

```
偽代碼：

SQL（透過已傳入的 cur）：
  SELECT b.booking_id, b.user_id, b.schedule_id,
         b.travel_date, b.status, b.booked_at
  FROM national_rail_bookings b
  LEFT JOIN users u ON b.user_id = u.user_id
  WHERE u.user_id IS NULL

rows = cur.fetchall()

records = []
repair_sql = []
for row in rows:
    records.append({
        "booking_id":  row["booking_id"],
        "user_id":     row["user_id"],
        "schedule_id": row["schedule_id"],
        "travel_date": row["travel_date"].isoformat(),   ← date → str
        "status":      row["status"],
        "booked_at":   row["booked_at"].isoformat(),     ← datetime → str
    })
    repair_sql.append(
        f"UPDATE national_rail_bookings "
        f"SET status = 'cancelled', cancellation_reason = 'DATA_INTEGRITY' "
        f"WHERE booking_id = '{row['booking_id']}';"
    )

return {
    "check":       "orphan_bookings",
    "description": "Bookings referencing a deleted or non-existent user",
    "status":      "FAIL" if records else "PASS",
    "count":       len(records),
    "records":     records,
    "repair_sql":  repair_sql,
}
```

**關鍵規格（測試掃描）**：
- `repair_sql` 每條必須含有對應的 `booking_id` 字串
- `repair_sql` 必須將 `status` 設為 `'cancelled'`
- `repair_sql` 的 `cancellation_reason` 欄位值必須包含 `'DATA_INTEGRITY'` 文字

---

#### check_schedule_time_logic(cur) → dict

```
偽代碼：

SQL：
  SELECT schedule_id, line, service_type, direction,
         origin_station_id, destination_station_id,
         first_train_time, last_train_time
  FROM national_rail_schedules
  WHERE first_train_time >= last_train_time

rows = cur.fetchall()

records = []
repair_sql = []
for row in rows:
    records.append({
        "schedule_id":      row["schedule_id"],
        "line":             row["line"],
        "direction":        row["direction"],
        "first_train_time": row["first_train_time"].isoformat(),   ← time → str
        "last_train_time":  row["last_train_time"].isoformat(),     ← time → str
    })
    repair_sql.append(
        f"DELETE FROM national_rail_schedules "
        f"WHERE schedule_id = '{row['schedule_id']}';"
    )

return {
    "check":       "schedule_time_logic",
    "description": "Schedules where first_train_time >= last_train_time",
    "status":      "FAIL" if records else "PASS",
    "count":       len(records),
    "records":     records,
    "repair_sql":  repair_sql,
}
```

**關鍵規格（測試掃描）**：
- `repair_sql` 每條必須含有對應的 `schedule_id` 字串
- `repair_sql` 必須包含 `DELETE` 關鍵字（大小寫不限）

---

#### check_capacity_consistency(cur) → dict

```
偽代碼：

SQL（JOIN seat_layouts + bookings，GROUP BY，HAVING）：
  SELECT
      nrsl.schedule_id,
      nrsl.layout_id,
      (SELECT COALESCE(SUM(jsonb_array_length(c -> 'seats')), 0)
       FROM jsonb_array_elements(nrsl.coaches) AS c)    AS total_seats,
      COUNT(b.booking_id) AS booking_count,
      COUNT(b.booking_id) -
      (SELECT COALESCE(SUM(jsonb_array_length(c -> 'seats')), 0)
       FROM jsonb_array_elements(nrsl.coaches) AS c)    AS overflow
  FROM national_rail_seat_layouts nrsl
  JOIN national_rail_bookings b
       ON nrsl.schedule_id = b.schedule_id
  WHERE b.status IN ('pending', 'confirmed')
  GROUP BY nrsl.schedule_id, nrsl.layout_id, nrsl.coaches
  HAVING COUNT(b.booking_id) > (
      SELECT COALESCE(SUM(jsonb_array_length(c -> 'seats')), 0)
      FROM jsonb_array_elements(nrsl.coaches) AS c
  )

← coaches JSONB 結構為 [{coach, fare_class, seats: [{seat_id, row, column}, ...]}, ...]
  jsonb_array_elements(nrsl.coaches) 把每個車廂物件展開為一列（lateral）
  jsonb_array_length(c -> 'seats') 取得該車廂的座位數
  SUM(...) 加總所有車廂 → 該班次的總座位數
  COALESCE(..., 0) 防止 coaches 為空陣列時回傳 NULL

rows = cur.fetchall()

records = []
repair_sql = []
for row in rows:
    overflow = int(row["overflow"])
    records.append({
        "schedule_id":   row["schedule_id"],
        "layout_id":     row["layout_id"],
        "total_seats":   int(row["total_seats"]),
        "booking_count": int(row["booking_count"]),
        "overflow":      overflow,
    })
    repair_sql.append(
        f"UPDATE national_rail_bookings SET status = 'cancelled' "
        f"WHERE booking_id IN ("
        f"  SELECT booking_id FROM national_rail_bookings "
        f"  WHERE schedule_id = '{row['schedule_id']}' "
        f"  AND status IN ('pending', 'confirmed') "
        f"  ORDER BY booked_at DESC "
        f"  LIMIT {overflow}"
        f");"
    )

return {
    "check":       "capacity_consistency",
    "description": "Schedules with more confirmed/pending bookings than total seats",
    "status":      "FAIL" if records else "PASS",
    "count":       len(records),
    "records":     records,
    "repair_sql":  repair_sql,
}
```

**關鍵規格（測試掃描）**：
- `records` 必須含 `overflow` 欄位，其值 = `booking_count - total_seats`
- `repair_sql` 每條必須含有對應的 `schedule_id` 字串
- `repair_sql` 的 `LIMIT` 子句數值必須等於 `overflow`（例如 `LIMIT 5`）
- 修復方式是 `UPDATE` 設為 `'cancelled'`，**不是** `DELETE`

---

#### run_checks(conn) → dict

```
偽代碼：

from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone

with conn.cursor(cursor_factory=RealDictCursor) as cur:
    # 第一步：設定唯讀交易（必須是第一個 execute 呼叫）
    cur.execute("SET TRANSACTION READ ONLY")

    # 第二步：依序執行三項子檢查（共用同一個 cur）
    orphan_result   = check_orphan_bookings(cur)
    time_result     = check_schedule_time_logic(cur)
    capacity_result = check_capacity_consistency(cur)

# 第三步：判斷總體狀態
all_pass = all(r["status"] == "PASS"
               for r in [orphan_result, time_result, capacity_result])

return {
    "report_generated_at": datetime.now(timezone.utc).isoformat(),
    "overall_status":      "PASS" if all_pass else "FAIL",
    "checks": [orphan_result, time_result, capacity_result],
    "summary": {
        "orphan_bookings":         orphan_result["count"],
        "invalid_time_schedules":  time_result["count"],
        "over_capacity_schedules": capacity_result["count"],
    },
}
```

**關鍵規格（測試掃描）**：
- `cur.execute` 的第一次呼叫 SQL 必須包含 `"READ ONLY"` 文字
- 回傳 dict 必須含 `"report_generated_at"`、`"overall_status"`、`"checks"`、`"summary"` 四個頂層 key
- `"checks"` 清單恰好 3 個元素，`"check"` 欄位依序為 `"orphan_bookings"`、`"schedule_time_logic"`、`"capacity_consistency"`
- `"summary"` 的 key 固定為 `"orphan_bookings"`、`"invalid_time_schedules"`、`"over_capacity_schedules"`
- **絕對不呼叫 `conn.commit()`**（測試以 `conn.commit.assert_not_called()` 驗證）
- 完整報告可直接 `json.dumps(report, default=str)` 序列化

---

#### apply_repairs(conn, report) → dict

```
偽代碼：

from datetime import datetime, timezone

executed = 0
failed   = 0
failures = []

with conn.cursor() as cur:
    for check in report["checks"]:
        for sql_str in check.get("repair_sql", []):
            # 略過純註解 SQL（每行非空都以 '--' 開頭）
            non_comment_lines = [
                line for line in sql_str.splitlines()
                if line.strip() and not line.strip().startswith("--")
            ]
            if not non_comment_lines:
                continue   # 跳過，不計入 executed_count

            try:
                cur.execute(sql_str)
                conn.commit()
                executed += 1
            except Exception as e:
                conn.rollback()
                failed += 1
                failures.append({"sql": sql_str, "error": str(e)})

return {
    "repair_applied_at": datetime.now(timezone.utc).isoformat(),
    "executed_count":    executed,
    "failed_count":      failed,
    "failures":          failures,
}
```

**關鍵規格（測試掃描）**：
- 回傳 dict 必須含 `"repair_applied_at"`、`"executed_count"`、`"failed_count"`、`"failures"` 四個 key
- 成功執行後立即呼叫 `conn.commit()`（每條 SQL 各 commit 一次）
- 執行失敗時立即呼叫 `conn.rollback()`，計入 `failed_count`
- 純註解 SQL（所有非空行均以 `--` 開頭）：**不執行、不計入 `executed_count`**

---

**執行測試**：
```bash
pytest tests/unit/ -v -k "maintenance_check"
```

---

### skeleton/agent.py 更新

在 `_execute_tool` 方法中整合計時和指標：

```python
from time import perf_counter
from skeleton.logging_config import StructuredLogger
from skeleton.metrics import query_counter, query_duration

_logger = StructuredLogger("transitflow.agent")  # 模組層級 logger

class TransitFlowAgent:
    @error_handler
    def _execute_tool(self, tool_name: str, params: dict) -> str:
        start = perf_counter()
        
        # ... 工具派遣邏輯 ...
        result = ...
        
        duration_ms = (perf_counter() - start) * 1000
        _logger.info("tool_executed", tool=tool_name, duration_ms=duration_ms, status="success")
        query_counter.labels(tool=tool_name, status="success").inc()
        query_duration.labels(tool=tool_name).observe(perf_counter() - start)
        
        return result
    
    def run(self, message, history, stream=False, progress_callback=None, session_id=None):
        # ... LLM 迴圈 ...
        # 每次呼叫 _execute_tool 前，如果 progress_callback 不為 None：
        if progress_callback:
            progress_callback(tool_name)
        # ... 繼續 ...
```

**關鍵規格**（靜態原始碼掃描）：
- `skeleton/agent.py` 含有 `"StructuredLogger"`
- `skeleton/agent.py` 含有 `"_logger"`
- `skeleton/agent.py` 含有 `"perf_counter"`
- `skeleton/agent.py` 含有 `"duration_ms"`
- `skeleton/agent.py` 含有 `"query_counter"`
- `skeleton/agent.py` 含有 `"progress_callback"`

**`progress_callback` 規格**：
- `run()` 方法簽名包含 `progress_callback=None`
- `run_agent()` 函式簽名也包含 `progress_callback=None`
- 每個被執行的工具觸發一次 `progress_callback(tool_name)`（字串）
- 沒有工具被執行時，`progress_callback` 不被呼叫
- 兩個工具被執行時，`progress_callback` 被呼叫兩次，各傳對應工具名稱

---

### skeleton/ui.py 更新 — chat() 生成器

```python
_TOOL_STATUS = {
    "search_policy":                     "🔄 正在搜尋政策文件...",
    "find_route":                         "🔄 正在計算最佳路線...",
    "check_national_rail_availability":   "🔄 正在查詢國鐵班次...",
    "check_metro_availability":           "🔄 正在查詢捷運班次...",
    "make_booking":                       "🔄 正在處理訂票...",
    "cancel_booking":                     "🔄 正在處理取消...",
    "get_available_seats":                "🔄 正在查詢可用座位...",
    "get_user_profile":                   "🔄 正在載入使用者資料...",
    "get_user_bookings":                  "🔄 正在取得訂票記錄...",
    "get_delay_ripple":                   "🔄 正在分析延誤影響...",
    # 可以有更多，至少 10 個
}

def chat(message, history, system_prompt, stream, session_id):
    if not message or not message.strip():
        return   # 空訊息不 yield 任何東西（成為空生成器）
    
    # 第一個 yield：立即顯示使用者訊息 + 思考中佔位符
    new_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": "🔄 思考中..."},
    ]
    yield new_history, []
    
    # 執行代理（同步呼叫）
    answer, tool_calls = run_agent(message, history, stream, None, session_id)
    
    # 最終 yield：真實答案
    final_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    yield final_history, tool_calls
```

**關鍵規格**：
- `chat()` 必須是生成器函式（含 `yield`，`inspect.isgeneratorfunction(chat)` 回傳 `True`）
- `chat()` 原始碼不含 `time.sleep`
- `_TOOL_STATUS` 是 `dict` 型態
- `_TOOL_STATUS` 至少有 10 個 key
- 必須包含 key：`"search_policy"`、`"find_route"`、`"check_national_rail_availability"`、`"check_metro_availability"`、`"make_booking"`
- 每個 value 都含有 `🔄` 字元
- 空訊息時不 yield 任何東西（`list(chat("  ", ...)) == []`）
- 第一個 yield 的 history 中，有 `role="user"` 且 content 含使用者訊息
- 第一個 yield 的 history 中，有 `role="assistant"` 且 content 含 `🔄`
- 最後一個 yield 的 history 中，assistant 的 content 是真實答案
- 至少 yield 2 次（初始佔位 + 最終答案）

---

## 驗收標準

**執行測試**：
```bash
pytest tests/unit/ -v -k "ui_observability"
```

---

## 全套驗收（最終門禁）

完成所有 Stage 3（`23`–`26`）後，執行完整測試套件：

```bash
pytest tests/ -v
```

**預期結果：524/524 PASS**

Stage 3 快速驗收：
```bash
pytest tests/unit/ -v -k "exception_layer"   # Stage 3.1
pytest tests/unit/ -v -k "solid_refactor"    # Stage 3.2
pytest tests/unit/ -v -k "performance_boost" # Stage 3.3
pytest tests/unit/ -v -k "ui_observability"  # Stage 3.4
```

若有失敗，優先檢查：
1. `_TOOL_STATUS` 是否含 `🔄` 且有 ≥10 個 key
2. `chat()` 是否有 `yield`（不是普通函式）
3. `_logger` 是否為模組層級（不是函式局部變數）
4. `stack_trace` 是否只在 `error(exc=...)` 時出現，沒有 `exc` 時不得有此欄位
5. `Neo4jConnectionPool.__exit__` 不能呼叫 `driver.close()`
