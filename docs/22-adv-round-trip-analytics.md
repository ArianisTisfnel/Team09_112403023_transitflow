# 22 — 進階功能｜來回票 + 三大分析函式

> **前置條件**：`07-A-query-nr-availability.md`、`08-A-query-nr-fare-metro-schedules.md` 完成
> **後續任務**：無（本任務為最終 Micro-task）

---

## 任務目標

在 `databases/relational/queries.py` 中實作四個進階業務函式：
`query_round_trip_itinerary`（來回票規劃）、`query_daily_revenue_report`（每日營收報告）、
`query_occupancy_forecast`（座位佔用率預測）、`query_user_loyalty_metrics`（使用者忠誠度指標）。

---

## 介面規格

### 函式一：`query_round_trip_itinerary`

```python
def query_round_trip_itinerary(
    origin_id: str,
    destination_id: str,
    outbound_date: str,
    return_date: str,
    fare_class: str = "standard",
) -> dict:
```

**回傳格式**：

```json
{
  "origin_id": "NR01",
  "destination_id": "NR05",
  "outbound_date": "2025-06-05",
  "return_date": "2025-06-10",
  "fare_class": "standard",
  "outbound_options": [...],
  "return_options": [...],
  "outbound_fare_usd": 12.50,
  "return_fare_usd": 12.50,
  "total_undiscounted_price": 25.00,
  "discount_rate": 0.15,
  "total_discounted_price": 21.25,
  "currency": "USD"
}
```

`return_date < outbound_date` 時拋出 `ValidationException`（不回傳 dict）。

---

### 函式二：`query_daily_revenue_report`

```python
def query_daily_revenue_report(date: str) -> dict:
```

**回傳格式**：

```json
{
  "date": "2025-06-01",
  "total_revenue_usd": 3250.00,
  "schedule_breakdown": [
    {
      "schedule_id": "NR_SCH01",
      "order_count": 45,
      "schedule_revenue_usd": 562.50,
      "total_seats": 120,
      "booked_seats": 45,
      "occupancy_rate": 37.50
    }
  ]
}
```

---

### 函式三：`query_occupancy_forecast`

```python
def query_occupancy_forecast(schedule_id: str, lead_days: int) -> dict:
```

**回傳格式**：

```json
{
  "schedule_id": "NR_SCH01",
  "total_seats": 120,
  "avg_daily_bookings": 3.5,
  "forecast": [
    {
      "forecast_date": "2025-06-02",
      "days_from_today": 1,
      "existing_bookings": 20,
      "predicted_total": 23.5,
      "predicted_occupancy_rate": 19.58
    }
  ],
  "error": null
}
```

`error = "SCHEDULE_NOT_FOUND"` 若班次不存在。

---

### 函式四：`query_user_loyalty_metrics`

```python
def query_user_loyalty_metrics(user_id: str) -> Optional[dict]:
```

**回傳格式**：

```json
{
  "user_id": "RU01",
  "total_orders": 8,
  "total_spending_usd": 125.00,
  "most_traveled_routes": [
    {"origin_station_id": "NR01", "destination_station_id": "NR05", "trip_count": 5}
  ],
  "badge_level": "Silver"
}
```

**徽章等級**：Bronze（< 5 筆）、Silver（5–19 筆）、Gold（>= 20 筆）
使用者不存在時回傳 `None`。

---

## 實作邏輯導引

### query_round_trip_itinerary 邏輯

```
偽代碼：

1. 解析並驗證日期：
   outbound = datetime.strptime(outbound_date, "%Y-%m-%d").date()
   ret = datetime.strptime(return_date, "%Y-%m-%d").date()
   
   if ret < outbound:
       raise ValidationException(
           "return_date must not be before outbound_date",
           "INVALID_DATE_ORDER"
       )

2. 呼叫已實作的函式（複用邏輯，無需重寫 SQL）：
   outbound_options = query_national_rail_availability(origin_id, destination_id, outbound_date)
   return_options = query_national_rail_availability(destination_id, origin_id, return_date)  ← 注意：方向相反
   
   outbound_fare_info = query_national_rail_fare(origin_id, destination_id, fare_class)
   return_fare_info = query_national_rail_fare(destination_id, origin_id, fare_class)  ← 注意：方向相反

3. 計算來回票折扣（15%）：
   outbound_fare_usd = outbound_fare_info["total_fare_usd"] if outbound_fare_info else 0.0
   return_fare_usd = return_fare_info["total_fare_usd"] if return_fare_info else 0.0
   total_undiscounted = round(outbound_fare_usd + return_fare_usd, 2)
   total_discounted = round(total_undiscounted * 0.85, 2)  ← 85% = 15% 折扣

4. 組裝並回傳 dict
```

**注意**：`ValidationException` 已在 `skeleton/exceptions.py` 中定義，
可直接 `from skeleton.exceptions import ValidationException` 使用。

### query_daily_revenue_report 邏輯

```
SQL 邏輯：

SELECT
    b.schedule_id,
    COUNT(b.booking_id)       AS order_count,
    SUM(b.amount_usd)         AS schedule_revenue_usd,
    sl.total_seats,
    COUNT(b.booking_id)       AS booked_seats,
    ROUND(COUNT(b.booking_id) * 100.0 / sl.total_seats, 2) AS occupancy_rate
FROM national_rail_bookings b
JOIN national_rail_seat_layouts sl ON b.schedule_id = sl.schedule_id
WHERE b.travel_date = $date
  AND b.status IN ('confirmed', 'completed')
GROUP BY b.schedule_id, sl.total_seats
ORDER BY b.schedule_id

Python 後處理：
  - schedule_revenue_usd 轉 float
  - occupancy_rate 轉 float
  - order_count 轉 int
  - total_revenue = round(sum of schedule_revenue_usd, 2)
```

### query_occupancy_forecast 邏輯

```
預測算法（兩段 SQL）：

第一段：取總座位數
  SELECT total_seats FROM national_rail_seat_layouts WHERE schedule_id = $schedule_id
  若無結果 → return {..., error: "SCHEDULE_NOT_FOUND"}

第二段：計算過去 7 天的每日平均新增訂票數
  SELECT COALESCE(AVG(daily_count), 0) AS avg_daily
  FROM (
      SELECT DATE(booked_at) AS booking_day, COUNT(*) AS daily_count
      FROM national_rail_bookings
      WHERE schedule_id = $schedule_id
        AND status IN ('confirmed', 'completed', 'pending')
        AND booked_at >= NOW() - INTERVAL '7 days'
        AND booked_at < NOW()
      GROUP BY DATE(booked_at)
  ) daily_counts

第三段：取未來 lead_days 天的現有訂票數
  SELECT travel_date, COUNT(*) AS existing_count
  FROM national_rail_bookings
  WHERE schedule_id = $schedule_id
    AND status IN ('confirmed', 'pending')
    AND travel_date > CURRENT_DATE
    AND travel_date <= CURRENT_DATE + $lead_days * INTERVAL '1 day'
  GROUP BY travel_date

Python 預測邏輯：
  today = date.today()
  for i in range(1, lead_days + 1):
      fdate = today + timedelta(days=i)
      existing = existing_by_date.get(fdate.isoformat(), 0)
      predicted_total = min(existing + avg_daily * i, total_seats)  ← 不超過上限
      predicted_occupancy = round(predicted_total / total_seats * 100, 2)
```

### query_user_loyalty_metrics 邏輯

```
SQL 分三段：

第一段：確認使用者存在
  SELECT user_id FROM users WHERE user_id = $user_id
  若無結果 → return None

第二段：統計訂單數和消費總額
  SELECT COUNT(*) AS total_orders, COALESCE(SUM(amount_usd), 0) AS total_spending_usd
  FROM national_rail_bookings
  WHERE user_id = $user_id AND status IN ('confirmed', 'completed', 'pending')

第三段：找最常旅行的路線（支援並列第一）
  WITH route_counts AS (
      SELECT origin_station_id, destination_station_id, COUNT(*) AS trip_count
      FROM national_rail_bookings
      WHERE user_id = $user_id AND status IN ('confirmed', 'completed', 'pending')
      GROUP BY origin_station_id, destination_station_id
  )
  SELECT origin_station_id, destination_station_id, trip_count
  FROM route_counts
  WHERE trip_count = (SELECT MAX(trip_count) FROM route_counts)
  ORDER BY origin_station_id ASC, destination_station_id ASC

Python 徽章計算：
  if total_orders >= 20: badge = "Gold"
  elif total_orders >= 5: badge = "Silver"
  else: badge = "Bronze"
```

---

## 驗收標準

**驗收測試**：

**query_round_trip_itinerary 測試驗證**：
1. 正常來回票：`total_discounted_price = round(total_undiscounted * 0.85, 2)`
2. `return_date < outbound_date` 拋出 `ValidationException`（不是回傳錯誤 dict）
3. `outbound_options` 和 `return_options` 分別對應兩個方向的可用班次

**query_daily_revenue_report 測試驗證**：
1. 有訂票的日期回傳非空 `schedule_breakdown`
2. `total_revenue_usd = sum(schedule_revenue_usd for all schedules)`
3. `occupancy_rate = round(booked_seats * 100.0 / total_seats, 2)`

**query_occupancy_forecast 測試驗證**：
1. 有效 schedule_id 回傳 `error=null`，`forecast` 陣列長度 = `lead_days`
2. 無效 schedule_id 回傳 `error="SCHEDULE_NOT_FOUND"`
3. `predicted_total` 不超過 `total_seats`（被 `min()` 限制）

**query_user_loyalty_metrics 測試驗證**：
1. 0 筆訂票 → badge="Bronze"
2. 5 筆訂票 → badge="Silver"
3. 20+ 筆訂票 → badge="Gold"
4. 並列最常旅行路線（同旅行次數）全部回傳
5. 不存在的 user_id 回傳 `None`

**執行測試**：
```bash
pytest tests/unit/ -v -k "round_trip_itinerary"
pytest tests/unit/ -v -k "revenue_report or occupancy_forecast or loyalty_metrics"
```

---

## 全套驗收（最終門禁）

完成所有 22 個 Micro-task 後，執行完整測試套件：

```bash
pytest tests/ -v
```

**預期結果：524/524 PASS**

若有失敗，優先檢查：
1. 函式簽名是否與規格完全一致（參數名稱、型態、預設值）
2. 回傳 dict 的欄位名稱是否正確（測試通常用 `result["field"]` 取值）
3. 邊界情境的回傳值（`None` vs `[]` vs `{}`）
4. 例外型態是否正確（`ValidationException` 而非 `ValueError`）
