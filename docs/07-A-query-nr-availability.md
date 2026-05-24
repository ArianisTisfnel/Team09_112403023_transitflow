# 07 — 主軸 A｜國鐵可用班次查詢（含動態座位計算）

> **前置條件**：`05-A-schema-transit-tables.md` 完成
> **後續任務**：`08-A-query-nr-fare-metro-schedules.md`、`21-adv-fallback-date-range.md`

---

## 任務目標

在 `databases/relational/queries.py` 中實作 `query_national_rail_availability`，
支援「指定日期」與「未來 14 天窗口」兩種查詢模式，並動態計算剩餘座位數。

---

## 介面規格

**目標檔案**：`databases/relational/queries.py`

```python
def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
```

**輸入**：

| 參數 | 型態 | 說明 |
|---|---|---|
| `origin_id` | `str` | 出發站 ID（如 `"NR01"`） |
| `destination_id` | `str` | 目的站 ID（如 `"NR05"`） |
| `travel_date` | `Optional[str]` | `"YYYY-MM-DD"` 或 `None`（None 時查未來 14 天） |

**回傳格式**（list，每個元素：）：

```json
{
  "schedule_id": "NR_SCH01",
  "line": "NR1",
  "direction": "northbound",
  "origin_station_id": "NR01",
  "destination_station_id": "NR05",
  "first_train_time": "07:30:00",
  "last_train_time": "20:30:00",
  "base_fare_usd": 12.50,
  "travel_date": "2025-06-01",
  "total_seats": 120,
  "booked_seats": 45,
  "available_seats": 75
}
```

**過濾條件**：`available_seats > 0`（客滿的班次不回傳）
**排序**：`travel_date ASC, schedule_id ASC`
**錯誤處理**：無可用班次時回傳 `[]`（空串列），不拋出例外。

---

## 實作邏輯導引

### 核心設計：以 WITH 子句（CTE）動態計算座位

本函式的精髓在於**不依賴靜態欄位**，而是在查詢時即時計算 `available_seats`：

```
可用座位數 = 總座位數（from seat_layouts）
           - 已訂座位數（from bookings WHERE status IN ('confirmed','pending')）
```

這個計算必須在 SQL 層完成（而非 Python 層），以確保並發正確性。

### 模式一：指定 travel_date

```
偽代碼（SQL 邏輯）：

WITH bookings_count AS (
  -- 子查詢：計算指定日期、指定狀態的已訂座位數
  -- 按 schedule_id 分組
  SELECT schedule_id,
         $travel_date AS travel_date,
         COUNT(*) AS booked_seats
  FROM national_rail_bookings
  WHERE status IN ('confirmed', 'pending')
    AND travel_date = $travel_date
  GROUP BY schedule_id
)
SELECT
  s.schedule_id, s.line, s.direction,
  s.origin_station_id, s.destination_station_id,
  s.first_train_time, s.last_train_time, s.base_fare_usd,
  $travel_date AS travel_date,
  sl.total_seats,
  COALESCE(bc.booked_seats, 0) AS booked_seats,
  sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats
FROM national_rail_schedules s
LEFT JOIN national_rail_seat_layouts sl ON s.schedule_id = sl.schedule_id
LEFT JOIN bookings_count bc ON s.schedule_id = bc.schedule_id
WHERE s.origin_station_id = $origin_id
  AND s.destination_station_id = $destination_id
  AND sl.total_seats - COALESCE(bc.booked_seats, 0) > 0  -- 過濾客滿班次
ORDER BY s.schedule_id ASC
```

**為什麼用 LEFT JOIN 而非 INNER JOIN？**
因為沒有任何訂票的班次在 `bookings_count` CTE 中不會出現，
用 LEFT JOIN 配合 `COALESCE(bc.booked_seats, 0)` 可以正確將這些班次視為「完全空」。

**為什麼 `travel_date` 參數要出現三次？**
psycopg2 的參數化查詢以位置為準（`%s`），
每個 `%s` 佔位符對應一個參數值，同一個邏輯值在 SQL 中出現幾次就要傳入幾次。

### 模式二：未來 14 天窗口（travel_date 為 None）

```
偽代碼（SQL 邏輯）：

WITH date_range AS (
  -- 生成今天起 14 天的日期序列
  SELECT CAST(CURRENT_DATE AS DATE) + i::INTEGER AS travel_date
  FROM GENERATE_SERIES(0, 13) AS i
),
bookings_count AS (
  -- 計算 14 天視窗內各班次各日期的已訂座位
  SELECT schedule_id, travel_date, COUNT(*) AS booked_seats
  FROM national_rail_bookings
  WHERE status IN ('confirmed', 'pending')
    AND travel_date >= CURRENT_DATE
    AND travel_date <= CURRENT_DATE + INTERVAL '13 days'
  GROUP BY schedule_id, travel_date
)
SELECT
  s.schedule_id, s.line, s.direction, ...,
  dr.travel_date,
  sl.total_seats,
  COALESCE(bc.booked_seats, 0) AS booked_seats,
  sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats
FROM national_rail_schedules s
CROSS JOIN date_range dr   -- 每個班次與每個日期組合
LEFT JOIN national_rail_seat_layouts sl ON s.schedule_id = sl.schedule_id
LEFT JOIN bookings_count bc
  ON s.schedule_id = bc.schedule_id AND bc.travel_date = dr.travel_date
WHERE s.origin_station_id = $origin_id
  AND s.destination_station_id = $destination_id
  AND sl.total_seats - COALESCE(bc.booked_seats, 0) > 0
ORDER BY dr.travel_date ASC, s.schedule_id ASC
```

**CROSS JOIN 的用途**：將每個班次（schedule）與 14 天中的每一天做笛卡爾積，
得到「班次 × 日期」所有組合，再用 LEFT JOIN 填入各組合的訂座數。

### Python 層實作結構

```
偽代碼（Python）：

def query_national_rail_availability(origin_id, destination_id, travel_date=None):
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if travel_date:
                cur.execute(<<模式一 SQL>>, (travel_date, travel_date, travel_date, origin_id, destination_id))
            else:
                cur.execute(<<模式二 SQL>>, (origin_id, destination_id))
            results = [dict(row) for row in cur.fetchall()]
    return results
```

**參數個數說明**（模式一）：SQL 中 `%s` 出現 5 次：
1. bookings_count 的 `$travel_date` 常量
2. bookings_count 的 `WHERE travel_date = $travel_date`
3. SELECT 清單中的 `$travel_date AS travel_date`
4. `WHERE origin_station_id = $origin_id`
5. `WHERE destination_station_id = $destination_id`

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：
1. 指定日期查詢：回傳該日期有座位的班次清單
2. None 查詢：回傳未來 14 天範圍內有座位的班次，含 `travel_date` 欄位
3. 客滿班次（`available_seats = 0`）不出現在結果中
4. 結果按 `travel_date ASC, schedule_id ASC` 排序
5. 每個 dict 包含 `total_seats`、`booked_seats`、`available_seats` 三個欄位
6. 無可用班次時回傳 `[]`

**執行測試**：
```bash
pytest tests/unit/ -v -k "national_rail_availability"
```
