# 21 — 進階功能｜替代班次回退 + 日期區間查詢

> **前置條件**：`07-A-query-nr-availability.md` 完成
> **後續任務**：`22-adv-round-trip-analytics.md`

---

## 任務目標

在 `databases/relational/queries.py` 中實作兩個進階查詢函式，
處理更複雜的業務情境：客滿後的替代班次搜尋，以及跨日期區間的班次查詢。

---

## 介面規格

### 函式一：`query_alternative_schedules_fallback`

```python
def query_alternative_schedules_fallback(schedule_id: str, travel_date: str) -> dict:
```

**輸入**：被搶完的班次 ID + 旅行日期

**回傳格式（找到替代方案）**：

```json
{
  "schedule_id": "NR_SCH01",
  "travel_date": "2025-06-01",
  "original_departure_time": "07:30",
  "alternatives": [
    {
      "schedule_id": "NR_SCH02",
      "line": "NR1",
      "direction": "northbound",
      "service_type": "normal",
      "origin_station_id": "NR01",
      "destination_station_id": "NR05",
      "departure_time": "08:30",
      "base_fare_usd": 12.50,
      "travel_date": "2025-06-01",
      "total_seats": 120,
      "booked_seats": 40,
      "available_seats": 80,
      "time_diff_seconds": 3600
    }
  ],
  "alternatives_found": 1,
  "error": null
}
```

**回傳格式（無替代 / 原班次不存在）**：

```json
{
  "schedule_id": "NR_SCH01",
  "travel_date": "2025-06-01",
  "original_departure_time": null,
  "alternatives": [],
  "alternatives_found": 0,
  "error": "SCHEDULE_NOT_FOUND"
}
```

**可能的 `error` 值**：`null`、`"SCHEDULE_NOT_FOUND"`、`"NO_ALTERNATIVES_FOUND"`、`"DATABASE_ERROR: ..."'`

---

### 函式二：`query_schedules_by_date_range`

```python
def query_schedules_by_date_range(
    origin_id: str,
    destination_id: str,
    start_date: str,
    end_date: str,
) -> dict:
```

**回傳格式**：

```json
{
  "origin_id": "NR01",
  "destination_id": "NR05",
  "start_date": "2025-06-01",
  "end_date": "2025-06-07",
  "schedules": [...],
  "total_found": 14,
  "error": null
}
```

**可能的 `error` 值**：`null`、`"INVALID_DATE_FORMAT"`、`"INVALID_DATE_RANGE"`（end < start）、`"DATE_RANGE_EXCEEDS_14_DAYS"`、`"DATABASE_ERROR: ..."`

---

## 實作邏輯導引

### query_alternative_schedules_fallback 核心邏輯

**業務規則**：
- 尋找同路線（相同 origin + destination）的其他班次
- 出發時間在原班次之後
- 時間差在 3 小時（10800 秒）以內
- 有剩餘座位（`available_seats > 0`）
- 最多回傳 3 班，按時間差由小到大排序

**跨午夜的時間差計算**（核心難點）：

```
假設 原班次出發時間 = 22:00（epoch 79200 秒）
     備選班次出發時間 = 01:00 次日（epoch 3600 秒）
     
直接相減：3600 - 79200 = -75600 → 負數，表示「提前出發」
但實際上：01:00 是隔天，正確差值應是 +3 小時 = 10800 秒

解法（MOD 算術）：
  diff = MOD((alt_epoch - orig_epoch + 86400), 86400)
       = MOD((-75600 + 86400), 86400)
       = MOD(10800, 86400)
       = 10800  ← 正確！3小時

規則：
  diff > 0     → 備選班次在原班次之後出發
  diff <= 10800 → 時間差在 3 小時以內
```

**SQL 邏輯（CTE + 跨午夜修正）**：

```
偽代碼（SQL）：

WITH original AS (
    SELECT origin_station_id, destination_station_id, first_train_time
    FROM national_rail_schedules
    WHERE schedule_id = $schedule_id
),
bookings_count AS (
    SELECT schedule_id, COUNT(*) AS booked_seats
    FROM national_rail_bookings
    WHERE status IN ('confirmed', 'pending')
      AND travel_date = $travel_date
    GROUP BY schedule_id
)
SELECT
    s.schedule_id, s.line, s.direction, s.service_type,
    s.origin_station_id, s.destination_station_id,
    TO_CHAR(s.first_train_time, 'HH24:MI') AS departure_time,
    s.base_fare_usd,
    $travel_date AS travel_date,
    sl.total_seats,
    COALESCE(bc.booked_seats, 0) AS booked_seats,
    sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats,
    -- 跨午夜 MOD 計算時間差
    MOD(
        (EXTRACT(EPOCH FROM s.first_train_time)
         - EXTRACT(EPOCH FROM o.first_train_time))::BIGINT + 86400,
        86400
    ) AS time_diff_seconds
FROM national_rail_schedules s
CROSS JOIN original o
LEFT JOIN national_rail_seat_layouts sl ON s.schedule_id = sl.schedule_id
LEFT JOIN bookings_count bc ON s.schedule_id = bc.schedule_id
WHERE s.origin_station_id = o.origin_station_id
  AND s.destination_station_id = o.destination_station_id
  AND s.schedule_id != $schedule_id           ← 排除原班次
  AND MOD(...)::BIGINT > 0                   ← 必須在原班次之後
  AND MOD(...)::BIGINT <= 10800              ← 3小時內
  AND sl.total_seats - COALESCE(bc.booked_seats, 0) > 0
ORDER BY time_diff_seconds ASC
LIMIT 3
```

**Python 層結構**（含例外處理）：

```
偽代碼（Python 函式骨架）：

def query_alternative_schedules_fallback(schedule_id, travel_date):
    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Step 1: 查詢原始班次確認存在
                cur.execute(<<查詢原始班次>>, (schedule_id,))
                original = cur.fetchone()
                
                if not original:
                    return {schedule_id: ..., travel_date: ...,
                            original_departure_time: None,
                            alternatives: [], alternatives_found: 0,
                            error: "SCHEDULE_NOT_FOUND"}
                
                # Step 2: 執行主要 CTE 查詢
                cur.execute(<<CTE 查詢>>, (schedule_id, travel_date, travel_date, schedule_id))
                alternatives = [dict(row) for row in cur.fetchall()]
                
                # 型態轉換
                for alt in alternatives:
                    alt["base_fare_usd"] = float(alt["base_fare_usd"])
                    alt["time_diff_seconds"] = int(alt["time_diff_seconds"])
                
                original_departure = str(original["first_train_time"])[:5]  # HH:MM
                
                if not alternatives:
                    return {..., error: "NO_ALTERNATIVES_FOUND"}
                
                return {..., alternatives: alternatives, alternatives_found: len(alternatives), error: None}
    
    except psycopg2.Error as db_error:
        return {..., error: f"DATABASE_ERROR: {str(db_error)}"}
```

### query_schedules_by_date_range 邏輯步驟

```
偽代碼：

1. Python 層驗證日期格式：
   try: datetime.strptime(start_date, "%Y-%m-%d")
   except ValueError: return {..., error: "INVALID_DATE_FORMAT"}

2. 驗證邏輯範圍：
   if end < start: return {..., error: "INVALID_DATE_RANGE"}
   if (end - start).days > 13: return {..., error: "DATE_RANGE_EXCEEDS_14_DAYS"}

3. 執行 CROSS JOIN 日期範圍查詢（與 07 的 14 天窗口邏輯類似）：
   WITH date_range AS (
       SELECT generate_series($start_date::DATE, $end_date::DATE, INTERVAL '1 day')::DATE AS travel_date
   ),
   bookings_count AS (...)
   SELECT s.*, dr.travel_date, sl.total_seats, ...
   FROM national_rail_schedules s
   CROSS JOIN date_range dr
   LEFT JOIN ...
   WHERE s.origin_station_id = $origin_id AND s.destination_station_id = $destination_id
   ORDER BY dr.travel_date ASC, s.first_train_time ASC

4. 回傳 {schedules: [...], total_found: len(schedules), error: None}

5. except psycopg2.Error: return {..., error: f"DATABASE_ERROR: {str(db_error)}"}
```

---

## 驗收標準

**驗收測試**：

**query_alternative_schedules_fallback 測試驗證**：
1. 正常情況：找到 1–3 班替代車次，按 `time_diff_seconds` 排序
2. 原班次不存在：`error="SCHEDULE_NOT_FOUND"`
3. 無替代班次（3 小時內都客滿或沒有其他班次）：`error="NO_ALTERNATIVES_FOUND"`
4. 替代班次的 `departure_time` 格式為 `"HH:MM"`（字串，非 timedelta）
5. 跨午夜邊界情境：22:00 原班次，01:00 替代班次，時間差計算正確（= 10800 秒）

**query_schedules_by_date_range 測試驗證**：
1. 正常 7 天查詢：`total_found` 等於（班次數 × 天數）
2. `error="INVALID_DATE_FORMAT"` 當日期字串格式錯誤
3. `error="INVALID_DATE_RANGE"` 當 end < start
4. `error="DATE_RANGE_EXCEEDS_14_DAYS"` 當範圍超過 14 天
5. 邊界情境：start_date = end_date（單日查詢），`total_found > 0`

**執行測試**：
```bash
pytest tests/unit/ -v -k "alternative_schedules_fallback or schedules_by_date_range"
```
