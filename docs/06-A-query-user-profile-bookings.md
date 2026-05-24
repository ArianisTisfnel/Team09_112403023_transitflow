# 06 — 主軸 A｜使用者個人資料與訂票紀錄查詢

> **前置條件**：`05-A-schema-transit-tables.md` 完成（`users`、`national_rail_bookings`、`payments` 表已建立並種子化）
> **後續任務**：`10-A-execute-booking.md`（execute_booking 的成功結果可被此函式查詢到）

---

## 任務目標

在 `databases/relational/queries.py` 中實作以下三個唯讀查詢函式：
`query_user_profile`、`query_user_bookings`、`query_payment_info`。

---

## 介面規格

**目標檔案**：`databases/relational/queries.py`

### 函式一：`query_user_profile`

```python
def query_user_profile(user_id: str) -> Optional[dict]:
```

**輸入**：`user_id`（字串，如 `"RU01"`）

**回傳格式**：

```json
{
  "user_id": "RU01",
  "full_name": "Alice Johnson",
  "email": "alice@example.com",
  "phone": "+1-555-0101",
  "date_of_birth": "1990-01-01",
  "registered_at": "2024-01-15T10:30:00+00:00",
  "is_active": true
}
```

使用者不存在時回傳 `None`（不拋出例外）。
注意：**絕對不可**在回傳值中包含 `password`、`secret_question`、`secret_answer` 欄位。

---

### 函式二：`query_user_bookings`

```python
def query_user_bookings(user_id: str) -> list[dict]:
```

**輸入**：`user_id`（字串，如 `"RU01"`）

**回傳格式**（list，每個元素：）：

```json
{
  "booking_id": "BK-AB123C",
  "user_id": "RU01",
  "schedule_id": "NR_SCH01",
  "origin_station_id": "NR01",
  "destination_station_id": "NR05",
  "origin_name": "Central Station",
  "destination_name": "Stonehaven",
  "travel_date": "2025-06-01",
  "departure_time": "08:30:00",
  "ticket_type": "single",
  "fare_class": "standard",
  "coach": "A",
  "seat_id": "A05",
  "amount_usd": "15.50",
  "status": "confirmed",
  "booked_at": "2025-05-15T14:22:00+00:00",
  "travelled_at": null
}
```

無訂票時回傳空串列 `[]`（不回傳 `None`，不拋出例外）。
排序：`ORDER BY b.travel_date DESC, b.departure_time DESC`。

---

### 函式三：`query_payment_info`

```python
def query_payment_info(booking_id: str) -> Optional[dict]:
```

**輸入**：`booking_id`（字串，如 `"BK-AB123C"` 或 `"MT001"`）

**回傳格式**：

```json
{
  "payment_id": "PM-XY789Z",
  "booking_id": "BK-AB123C",
  "amount_usd": "15.50",
  "method": "credit_card",
  "status": "paid",
  "paid_at": "2025-05-15T14:22:00+00:00",
  "refunded_at": null
}
```

無付款紀錄時回傳 `None`。若有多筆（退款後有新紀錄），取 `paid_at DESC LIMIT 1`。

---

## 實作邏輯導引

### query_user_profile 邏輯步驟

```
偽代碼：
1. 呼叫 _connect() 取得連線（autocommit=True）
2. 使用 RealDictCursor 執行：
   SELECT user_id, full_name, email, phone, date_of_birth, registered_at, is_active
   FROM users
   WHERE user_id = %s
   參數：(user_id,)
3. 呼叫 fetchone()
4. 若結果為 None，回傳 None
5. 否則將 Row 轉換為 dict 後回傳
   （RealDictCursor 的 fetchone() 回傳類字典物件，
    需用 dict(result) 確保型別為純 Python dict）
```

**注意**：SELECT 清單中明確列出欄位名稱，絕不使用 `SELECT *`，
以防止 `password` 欄位洩漏給呼叫方。

### query_user_bookings 邏輯步驟

```
偽代碼：
1. 呼叫 _connect() 取得連線
2. 使用 RealDictCursor 執行 JOIN 查詢：
   SELECT
     b.booking_id, b.user_id, b.schedule_id,
     b.origin_station_id, b.destination_station_id,
     o.name AS origin_name,
     d.name AS destination_name,
     b.travel_date, b.departure_time, b.ticket_type,
     b.fare_class, b.coach, b.seat_id,
     b.amount_usd, b.status, b.booked_at, b.travelled_at
   FROM national_rail_bookings b
   JOIN national_rail_stations o
     ON b.origin_station_id = o.national_rail_station_id
   JOIN national_rail_stations d
     ON b.destination_station_id = d.national_rail_station_id
   WHERE b.user_id = %s
   ORDER BY b.travel_date DESC, b.departure_time DESC
   
   參數：(user_id,)
3. 將 fetchall() 的每一行轉換為 dict
4. 回傳 list（可能為空串列）
```

### query_payment_info 邏輯步驟

```
偽代碼：
1. 呼叫 _connect()
2. 執行：
   SELECT payment_id, booking_id, amount_usd, method, status, paid_at, refunded_at
   FROM payments
   WHERE booking_id = %s
   ORDER BY paid_at DESC
   LIMIT 1
   參數：(booking_id,)
3. fetchone()，若為 None 回傳 None，否則 dict(row)
```

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：
1. 存在的使用者回傳正確欄位集合（不含密碼欄位）
2. 不存在的 user_id 回傳 `None`
3. 有訂票的使用者回傳非空 list
4. 無訂票的使用者回傳 `[]`（空串列）
5. 回傳 list 中的每個 dict 包含 `origin_name` 和 `destination_name`（JOIN 結果）
6. `query_payment_info` 對已取消訂票回傳最新的付款紀錄

**執行測試**：
```bash
pytest tests/unit/ -v -k "user_profile or user_bookings or payment_info"
```
