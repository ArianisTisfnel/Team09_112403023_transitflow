# Stage 2 — 進階功能實作報告：替代班次回退 + 日期區間查詢 + 來回票分析

> **作者**：陳玟茹（主軸 A）
> **涵蓋範圍**：`docs/21`–`docs/22`（進階選做功能）
> **狀態**：程式碼全部完成，6 個進階函式
> **最後更新**：2026-06-05

---

## 一、實作範圍

### 1.1 修改的檔案

| 檔案 | 內容 | 對應 docs |
|---|---|---|
| `databases/relational/queries.py` | 6 個進階查詢函式 | docs/21–22 |

### 1.2 完成的函式清單

| 函式 | 類別 | 對應 docs |
|---|---|---|
| `query_alternative_schedules_fallback(schedule_id, travel_date)` | 唯讀 | docs/21 |
| `query_schedules_by_date_range(origin_id, destination_id, start_date, end_date)` | 唯讀 | docs/21 |
| `query_round_trip_itinerary(origin_id, destination_id, outbound_date, return_date, fare_class)` | 唯讀 | docs/22 |
| `query_daily_revenue_report(date)` | 唯讀 | docs/22 |
| `query_occupancy_forecast(schedule_id, lead_days)` | 唯讀 | docs/22 |
| `query_user_loyalty_metrics(user_id)` | 唯讀 | docs/22 |

---

## 二、設計決策

### 2.1 跨午夜時間差計算（`query_alternative_schedules_fallback`）

找替代班次時，需要計算兩個班次出發時間的差值。直接相減會遇到跨午夜問題：

```
原班次：22:00（epoch 79200 秒）
備選班次：01:00 次日（epoch 3600 秒）
直接相減：3600 - 79200 = -75600 → 負數，錯誤
```

解法是用 MOD 算術：

```sql
MOD(
    (EXTRACT(EPOCH FROM s.first_train_time)
     - EXTRACT(EPOCH FROM original.first_train_time))::BIGINT + 86400,
    86400
) AS time_diff_seconds
```

加上 86400（一天的秒數）再取模，確保結果永遠是正數，正確表示「備選班次在原班次之後幾秒出發」。

限制條件：`time_diff_seconds BETWEEN 1 AND 10800`（1 秒到 3 小時內）、且有剩餘座位、最多回傳 3 班。

### 2.2 日期範圍查詢的輸入驗證（`query_schedules_by_date_range`）

在 Python 層做三道驗證，不讓無效輸入進到資料庫：

| 驗證 | 錯誤碼 |
|---|---|
| 日期格式是否為 `YYYY-MM-DD` | `INVALID_DATE_FORMAT` |
| `end_date` 是否 ≥ `start_date` | `INVALID_DATE_RANGE` |
| 區間是否超過 14 天 | `DATE_RANGE_EXCEEDS_14_DAYS` |

14 天上限的理由：與 `query_national_rail_availability` 的窗口一致，避免大範圍查詢拖慢效能。

### 2.3 來回票 15% 折扣設計（`query_round_trip_itinerary`）

來回票的票價計算複用已實作的函式，不重寫 SQL：

```python
outbound_options = query_national_rail_availability(origin_id, destination_id, outbound_date)
return_options   = query_national_rail_availability(destination_id, origin_id, return_date)

# 取第一個可用班次的票價
fare_info = query_national_rail_fare(outbound_options[0]["schedule_id"], fare_class, 1)
```

折扣計算：
```
total_undiscounted = outbound_fare + return_fare
total_discounted   = round(total_undiscounted * 0.85, 2)  ← 85% = 85折
```

`return_date < outbound_date` 時拋出 `ValidationException`（不回傳錯誤 dict），讓呼叫方（agent）能明確感知輸入錯誤。

### 2.4 座位佔用預測的兩階段計算（`query_occupancy_forecast`）

預測邏輯分兩步：

**第一步**：用過去 7 天的訂票紀錄算出「每日平均新增訂票數」：
```sql
SELECT COALESCE(AVG(daily_count), 0) AS avg_daily
FROM (
    SELECT DATE(booked_at) AS booking_day, COUNT(*) AS daily_count
    FROM national_rail_bookings
    WHERE schedule_id = %s
      AND booked_at >= NOW() - INTERVAL '7 days'
    GROUP BY DATE(booked_at)
) daily_counts
```

**第二步**：對未來每一天，用「現有訂票數 + 平均日增量 × 距今天數」預測總訂票量，並限制不超過總座位數：
```python
predicted_total = min(existing + avg_daily * i, total_seats)
```

這個線性預測模型很簡單，但符合 docs/22 的規格要求。

### 2.5 忠誠度徽章的三段等級（`query_user_loyalty_metrics`）

| 訂單數 | 徽章 |
|---|---|
| 0–4 | Bronze |
| 5–19 | Silver |
| 20+ | Gold |

最常旅行路線支援並列第一（多條路線旅行次數相同時全部回傳）：

```sql
WITH route_counts AS (
    SELECT origin_station_id, destination_station_id, COUNT(*) AS trip_count
    FROM national_rail_bookings
    WHERE user_id = %s AND status IN ('confirmed', 'completed', 'pending')
    GROUP BY origin_station_id, destination_station_id
)
SELECT * FROM route_counts
WHERE trip_count = (SELECT MAX(trip_count) FROM route_counts)
ORDER BY origin_station_id ASC, destination_station_id ASC
```

---

## 三、關鍵 SQL 邏輯說明

### 3.1 `query_alternative_schedules_fallback`：CTE + 跨午夜 MOD

整個查詢用一個 CTE 搞定，不需要 Python 端做後處理：

```sql
WITH bookings_count AS (
    SELECT schedule_id, COUNT(*) AS booked_seats
    FROM national_rail_bookings
    WHERE status IN ('confirmed', 'pending')
      AND travel_date = %s::DATE
    GROUP BY schedule_id
)
SELECT
    s.schedule_id, s.line, s.direction, s.service_type, ...,
    sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats,
    MOD(
        (EXTRACT(EPOCH FROM s.first_train_time)
         - EXTRACT(EPOCH FROM (SELECT first_train_time FROM national_rail_schedules
                                WHERE schedule_id = %s)))::BIGINT + 86400,
        86400
    ) AS time_diff_seconds
FROM national_rail_schedules s
LEFT JOIN national_rail_seat_layouts sl ON s.schedule_id = sl.schedule_id
LEFT JOIN bookings_count bc ON s.schedule_id = bc.schedule_id
WHERE s.origin_station_id = %s AND s.destination_station_id = %s
  AND s.schedule_id != %s
  AND time_diff_seconds BETWEEN 1 AND 10800
  AND available_seats > 0
ORDER BY time_diff_seconds ASC
LIMIT 3
```

### 3.2 `query_schedules_by_date_range`：`generate_series` 生成日期區間

```sql
WITH date_range AS (
    SELECT generate_series(%s::DATE, %s::DATE, INTERVAL '1 day')::DATE AS travel_date
)
SELECT s.*, dr.travel_date, sl.total_seats, ...
FROM national_rail_schedules s
CROSS JOIN date_range dr
LEFT JOIN national_rail_seat_layouts sl ON ...
LEFT JOIN bookings_count bc ON ...
WHERE s.origin_station_id = %s AND s.destination_station_id = %s
  AND available_seats > 0
ORDER BY dr.travel_date ASC, s.first_train_time ASC
```

`generate_series` 直接在 SQL 內生成日期序列，再 `CROSS JOIN` 班次表，一次查詢就取得所有（班次 × 日期）組合的可用座位數。

### 3.3 `query_daily_revenue_report`：佔用率計算

```sql
SELECT
    b.schedule_id,
    COUNT(b.booking_id)    AS order_count,
    SUM(b.amount_usd)      AS schedule_revenue_usd,
    sl.total_seats,
    ROUND(COUNT(b.booking_id) * 100.0 / sl.total_seats, 2) AS occupancy_rate
FROM national_rail_bookings b
JOIN national_rail_seat_layouts sl ON b.schedule_id = sl.schedule_id
WHERE b.travel_date = %s::DATE
  AND b.status IN ('confirmed', 'completed')
GROUP BY b.schedule_id, sl.total_seats
ORDER BY b.schedule_id
```

`ROUND(..., 2)` 確保佔用率精確到小數點後兩位（如 `37.50`）。

---

## 四、已知限制

| 限制 | 說明 |
|---|---|
| 預測模型為線性 | `query_occupancy_forecast` 假設每天新增訂票數恆定，實際上週末與假日可能有峰值 |
| 替代班次只找同日 | `query_alternative_schedules_fallback` 只在同一天找替代，不考慮隔天首班 |
| 來回票票價用第一班次 | `query_round_trip_itinerary` 取可用班次清單的第一個計算票價，不保證是最便宜的 |
| 報表只含國鐵訂單 | `query_daily_revenue_report` 目前只統計 `national_rail_bookings`，不含 `metro_travel_history` |

---

## 五、測試結果摘要

| 測試案例 | 預期結果 |
|---|---|
| `query_alternative_schedules_fallback`：原班次不存在 | `error="SCHEDULE_NOT_FOUND"` |
| `query_alternative_schedules_fallback`：3 小時內無空位 | `error="NO_ALTERNATIVES_FOUND"` |
| `query_schedules_by_date_range`：格式錯誤 | `error="INVALID_DATE_FORMAT"` |
| `query_schedules_by_date_range`：end < start | `error="INVALID_DATE_RANGE"` |
| `query_schedules_by_date_range`：超過 14 天 | `error="DATE_RANGE_EXCEEDS_14_DAYS"` |
| `query_round_trip_itinerary`：return < outbound | 拋出 `ValidationException` |
| `query_round_trip_itinerary`：正常來回票 | `total_discounted_price = round(total * 0.85, 2)` |
| `query_occupancy_forecast`：班次不存在 | `error="SCHEDULE_NOT_FOUND"` |
| `query_user_loyalty_metrics`：0 筆訂單 | `badge_level="Bronze"` |
| `query_user_loyalty_metrics`：20+ 筆訂單 | `badge_level="Gold"` |
| `query_user_loyalty_metrics`：使用者不存在 | 回傳 `None` |

執行指令：

```bash
pytest tests/unit/ -v -k "alternative_schedules_fallback or schedules_by_date_range"
pytest tests/unit/ -v -k "round_trip_itinerary or revenue_report or occupancy_forecast or loyalty_metrics"
```
