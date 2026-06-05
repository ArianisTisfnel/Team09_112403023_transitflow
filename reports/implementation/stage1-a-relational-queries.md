# Stage 1 — 主軸 A 實作報告：PostgreSQL 關聯式資料庫層

> **作者**：陳玟茹（主軸 A）
> **涵蓋範圍**：`docs/04`–`docs/12`（主軸 A 全部必做任務）+ `docs/21`–`docs/22`（進階選做）
> **狀態**：程式碼全部完成，schema 10 張表，查詢函式 21 個
> **最後更新**：2026-06-05

---

## 一、實作範圍

### 1.1 修改的檔案

| 檔案 | 內容 | 對應 docs |
|---|---|---|
| `databases/relational/schema.sql` | 10 張業務表 + pgvector 向量表 + 19 個索引 | docs/04–05 |
| `databases/relational/queries.py` | 21 個查詢 / 寫入 / 認證函式 | docs/06–12, 21–22 |

### 1.2 完成的函式清單

#### Schema（`databases/relational/schema.sql`）

| 表名 | 說明 |
|---|---|
| `users` | 使用者帳戶，含 argon2 雜湊密碼、密保問答 |
| `national_rail_stations` | 國鐵站點，JSONB 儲存所屬路線，可選關聯地鐵轉乘站 |
| `metro_stations` | 地鐵站點，JSONB 儲存所屬路線，可選關聯國鐵轉乘站 |
| `metro_station_adjacencies` | 地鐵相鄰站點有向圖，每條 (origin, destination, line) 一列 |
| `metro_schedules` | 地鐵班次（起訖站、首末班時間、票價、運行日） |
| `national_rail_schedules` | 國鐵班次（起訖站、首末班時間、票價、服務類型） |
| `national_rail_seat_layouts` | 國鐵座位配置（JSONB 儲存車廂與座位清單） |
| `national_rail_bookings` | 國鐵訂單，含座位、票類、票價、狀態機 |
| `metro_travel_history` | 地鐵出行紀錄 |
| `payments` | 付款紀錄，使用多型關聯（booking_id 可對應兩種訂單） |
| `policy_documents` | pgvector RAG 表（課程提供，未修改） |

#### 查詢函式（`databases/relational/queries.py`）

| 函式 | 類別 | 對應 docs |
|---|---|---|
| `query_user_profile(user_email)` | 唯讀 | docs/06 |
| `query_user_bookings(user_email)` | 唯讀 | docs/06 |
| `query_payment_info(booking_id)` | 唯讀 | docs/06 |
| `query_national_rail_availability(origin_id, destination_id, travel_date)` | 唯讀 | docs/07 |
| `query_national_rail_fare(schedule_id, fare_class, stops_travelled)` | 唯讀 | docs/08 |
| `query_metro_schedules(origin_id, destination_id)` | 唯讀 | docs/08 |
| `query_metro_fare(schedule_id, stops_travelled)` | 唯讀 | docs/09 |
| `query_available_seats(schedule_id, travel_date, fare_class)` | 唯讀 | docs/09 |
| `auto_select_adjacent_seats(available_seats, count)` | 純 Python | docs/09 |
| `execute_booking(...)` | 寫入（事務） | docs/10 |
| `execute_cancellation(booking_id, reason)` | 寫入（事務） | docs/11 |
| `register_user(...)` | 寫入（事務） | docs/12 |
| `login_user(email, password)` | 唯讀 | docs/12 |
| `get_user_secret_question(email)` | 唯讀 | docs/12 |
| `verify_secret_answer(email, answer)` | 唯讀 | docs/12 |
| `update_password(email, new_password)` | 寫入 | docs/12 |
| `query_alternative_schedules_fallback(schedule_id, travel_date)` | 唯讀 | docs/21（選做） |
| `query_schedules_by_date_range(origin_id, destination_id, start_date, end_date)` | 唯讀 | docs/21（選做） |
| `query_round_trip_itinerary(origin_id, destination_id, outbound_date, return_date, fare_class)` | 唯讀 | docs/22（選做） |
| `query_daily_revenue_report(date)` | 唯讀 | docs/22（選做） |
| `query_occupancy_forecast(schedule_id, lead_days)` | 唯讀 | docs/22（選做） |
| `query_user_loyalty_metrics(user_id)` | 唯讀 | docs/22（選做） |

---

## 二、設計決策

### 2.1 為什麼 `national_rail_stations` 和 `metro_stations` 用雙向外鍵？

兩張站點表互相參照（國鐵站 → 對應地鐵轉乘站，地鐵站 → 對應國鐵轉乘站），形成循環外鍵。

直接用普通 `FOREIGN KEY` 會在建表時就因為對方還不存在而報錯。解法是先建兩張表本體，之後再用 `ALTER TABLE ... ADD CONSTRAINT ... DEFERRABLE INITIALLY DEFERRED` 補上外鍵。

`DEFERRABLE INITIALLY DEFERRED` 的意思是：外鍵檢查延遲到整個交易 commit 時才做，而不是每一行 INSERT 後立刻檢查。這樣在同一個交易裡可以先插國鐵站、再插地鐵站，兩邊互相參照也不會衝突。

```sql
-- 先建表（沒有外鍵）
CREATE TABLE national_rail_stations (...);
CREATE TABLE metro_stations (...);

-- 再補循環外鍵
ALTER TABLE national_rail_stations
    ADD CONSTRAINT fk_nr_interchange_metro
    FOREIGN KEY (interchange_metro_station_id)
    REFERENCES metro_stations(metro_station_id)
    DEFERRABLE INITIALLY DEFERRED;
```

### 2.2 座位配置為什麼用 JSONB 而不是拆成獨立表？

座位資料（`national_rail_seat_layouts.coaches`）用 JSONB 儲存整個車廂結構，而不是每個座位一列。

比較兩種方式：

| 方式 | 優點 | 缺點 |
|---|---|---|
| 每座位一列（正規化） | 可直接 SQL 查詢單一座位 | 一班次幾百個座位 → 表很大；查詢要 JOIN |
| JSONB（本方案） | 讀一筆就拿到全車廂配置，簡單快速 | 不能直接 SQL 篩選 JSON 內部欄位 |

這個系統查詢座位的方式是「先拿整個車廂配置，再在 Python 端過濾已訂的座位」，所以 JSONB 反而更符合實際讀取模式，不需要 JOIN。

### 2.3 `execute_booking` 的防超賣機制

訂票時的座位衝突檢查用了 `SELECT ... FOR UPDATE`：

```sql
SELECT booking_id FROM national_rail_bookings
WHERE schedule_id = %s
  AND travel_date = %s
  AND seat_id = %s
  AND coach = %s
  AND status IN ('pending', 'confirmed')
FOR UPDATE LIMIT 1
```

`FOR UPDATE` 會對找到的列加行鎖，讓同時間的其他交易無法修改同一筆訂單。這樣兩個用戶同時搶同一個座位時，第二個人會等第一個人的交易 commit 或 rollback 後才繼續，而不是兩個人都成功插入。

### 2.4 `payments` 表的多型關聯設計

`payments.booking_id` 可以對應到 `national_rail_bookings.booking_id` 或 `metro_travel_history.trip_id`，兩個不同的表。

正常外鍵只能指向一張表，所以這裡**刻意不加外鍵**，改用應用層來確保一致性。這在 docs/05 的設計說明裡有明確記錄：

```sql
-- booking_id deliberately has no FK: it references either of two tables —
-- national_rail_bookings or metro_travel_history — a polymorphic association
```

### 2.5 密碼用 argon2 雜湊

`register_user` 儲存密碼前先用 `argon2-cffi` 的 `PasswordHasher` 做雜湊，`login_user` 驗證時用 `_ph.verify(hashed, plain)` 比對，不儲存明文。

argon2 比 bcrypt 和 SHA-256 的優勢：對 GPU 暴力破解的抵抗性更強（設計上就是記憶體密集型演算法）。

---

## 三、關鍵 SQL 邏輯說明

### 3.1 `query_national_rail_availability`：無日期時回傳 14 天可用班次

當呼叫者沒有指定 `travel_date` 時，用 `GENERATE_SERIES` 生成未來 14 天的日期序列，再 `CROSS JOIN` 班次表，同時算出每天每班次的剩餘座位數：

```sql
WITH date_range AS (
    SELECT CAST(CURRENT_DATE AS DATE) + i::INTEGER AS travel_date
    FROM GENERATE_SERIES(0, 13) AS i
),
bookings_count AS (
    SELECT schedule_id, travel_date, COUNT(*) AS booked_seats
    FROM national_rail_bookings
    WHERE status IN ('confirmed', 'pending')
      AND travel_date >= CURRENT_DATE
    GROUP BY schedule_id, travel_date
)
SELECT s.*, dr.travel_date,
       sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats
FROM national_rail_schedules s
CROSS JOIN date_range dr
LEFT JOIN national_rail_seat_layouts sl ON ...
LEFT JOIN bookings_count bc ON ...
WHERE available_seats > 0
```

`COALESCE(bc.booked_seats, 0)` 處理當天沒有任何訂單時 `bc` 為 NULL 的情況，確保計算不會因為 NULL 而出錯。

### 3.2 `query_national_rail_fare`：票價乘數表

票價根據 `fare_class` 乘以對應倍率，結果四捨五入到小數點後兩位：

| fare_class | 倍率 |
|---|---|
| standard | 1.0 |
| first | 1.5 |
| senior | 0.8 |
| student | 0.85 |

這個計算帶快取（`skeleton/cache.py`），相同的 `(schedule_id, fare_class, stops_travelled)` 組合只查一次資料庫。

### 3.3 `query_metro_fare`：三段票價區間

地鐵票價依照乘坐站數分三個區間：

| 站數 | 票價 |
|---|---|
| 1–2 站 | $1.50 |
| 3–5 站 | $2.50 |
| 6 站以上 | $4.00 |

### 3.4 `auto_select_adjacent_seats`：優先選同排座位

邏輯分兩步：

1. 先把可用座位按 `row` 分組，找到第一個「同排座位數 ≥ 需求數」的排，直接回傳那一排的前 N 個座位。
2. 如果找不到整排夠坐的，就把所有座位按 `(row, column)` 排序，取前 N 個（盡量靠近）。

```python
rows: dict[int, list[dict]] = defaultdict(list)
for seat in available_seats:
    rows[seat["row"]].append(seat)

for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
    if len(row_seats) >= count:
        return [s["seat_id"] for s in row_seats[:count]]

# fallback: sort globally
sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
return [s["seat_id"] for s in sorted_seats[:count]]
```

### 3.5 `query_alternative_schedules_fallback`：找 3 小時內的替代班次

當指定班次滿員時，找同路線、出發時間在原班次之後 0–180 分鐘內、且有空位的最多 3 班替代班次。時間差用 epoch 秒換算後取模 86400（處理跨午夜的情況）：

```sql
MOD(
    (EXTRACT(EPOCH FROM s.first_train_time)
     - EXTRACT(EPOCH FROM (SELECT first_train_time FROM ...)))::BIGINT + 86400,
    86400
) BETWEEN 1 AND 10800  -- 1 秒到 3 小時
```

---

## 四、已知限制

| 限制 | 說明 |
|---|---|
| `metro_travel_history` 無法訂票 | 目前 `execute_booking` 只支援國鐵；地鐵出行紀錄只能讀，不能透過 agent 新增 |
| `payments` 無外鍵 | 多型關聯的設計取捨，應用層沒有對 booking_id 做交叉驗證 |
| `feedback` 表未建立 | `train-mock-data/feedback.json` 有資料，但 schema 未設計此表，seeder 跳過 |
| 座位鎖在高併發下的邊界 | `FOR UPDATE` 在 `autocommit=True` 的連線下無效；`execute_booking` 已正確設為 `autocommit=False` |
| 票價快取 TTL | `fare_cache` 用 `lru_cache` 實作，重啟後失效，無跨進程共享 |

---

## 五、測試結果摘要

單元測試覆蓋以下函式（`tests/unit/`）：

| 測試檔案 | 涵蓋函式 |
|---|---|
| `test_query_nr_availability.py` | `query_national_rail_availability` |
| `test_query_nr_fare.py` | `query_national_rail_fare` |
| `test_query_metro_schedules.py` | `query_metro_schedules` |
| `test_query_available_seats.py` | `query_available_seats` |
| `test_execute_booking.py` | `execute_booking` |
| `test_execute_cancellation.py` | `execute_cancellation` |
| `test_query_user_profile.py` | `query_user_profile` |
| `test_query_user_bookings.py` | `query_user_bookings` |
| `test_query_alternative_schedules_fallback.py` | `query_alternative_schedules_fallback` |
| `test_query_schedules_by_date_range.py` | `query_schedules_by_date_range` |
| `test_query_round_trip_itinerary.py` | `query_round_trip_itinerary` |
| `test_analytics_tools.py` | `query_daily_revenue_report`、`query_occupancy_forecast`、`query_user_loyalty_metrics` |

整合測試（`tests/integration/`）在 Docker 環境下驗證真實資料庫連線，涵蓋 booking / cancellation / seat availability 的端對端流程。

執行指令：

```bash
# 單元測試（不需 DB）
pytest tests/unit/ -v --tb=short

# 整合測試（需 docker compose up -d）
pytest tests/integration/ -v --tb=short
```
