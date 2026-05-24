# 10 — 主軸 A｜建立訂票（原子交易 + 座位衝突偵測）

> **前置條件**：`07-A-query-nr-availability.md`、`09-A-query-metro-fare-seats.md`（`query_available_seats` 已實作）
> **後續任務**：`11-A-execute-cancellation.md`

---

## 任務目標

在 `databases/relational/queries.py` 中實作 `execute_booking`，
以原子交易方式完成國鐵訂票，包含座位衝突偵測、票價計算、自動選位、以及同步建立付款紀錄。

---

## 介面規格

**目標檔案**：`databases/relational/queries.py`

```python
def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,          # "any" 表示自動選位
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
```

**成功回傳**：

```json
(True, {
  "booking_id": "BK-AB123C",
  "payment_id": "PM-XY789Z",
  "user_id": "RU01",
  "schedule_id": "NR_SCH01",
  "origin_station_id": "NR01",
  "destination_station_id": "NR05",
  "travel_date": "2025-06-01",
  "departure_time": "07:30:00",
  "ticket_type": "single",
  "fare_class": "standard",
  "coach": "A",
  "seat_id": "A05",
  "base_fare_usd": 12.50,
  "fare_multiplier": 1.0,
  "total_fare_usd": 12.50,
  "status": "pending",
  "booked_at": "2025-05-15T14:22:00+00:00"
})
```

**失敗回傳**（各種錯誤情境）：

```python
(False, "User RU99 not found")
(False, "Schedule NR_SCH99 not found")
(False, "No available seats in first class for NR_SCH01 on 2025-06-01")
(False, "Seat A05 in coach A is already booked for NR_SCH01 on 2025-06-01")
(False, "Database error: ...")
```

---

## 實作邏輯導引

### 頂部輔助函式（scaffold 已存在，勿重複定義）

> ℹ️ `main` 分支的 scaffold 已包含這兩個 helper 的完整實作，**不需要自行定義，直接使用即可**。
> 若你重複定義同名函式，Python 會以後者覆蓋前者，不報錯但可能造成混淆。

`execute_booking` 依賴兩個私有 helper，已存在於 `databases/relational/queries.py` 頂部（`execute_booking` 函式之前）：

```
參考（scaffold 中的現有實作，不需修改）：

def _gen_booking_id() -> str:
    # "BK-" + 6 個隨機大寫英數字（A-Z + 0-9）
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"

def _gen_payment_id() -> str:
    # "PM-" + 6 個隨機大寫英數字
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"
```

測試只驗證 `booking_id` 以 `"BK-"` 開頭、`payment_id` 以 `"PM-"` 開頭，不驗證長度或字元集，但維持 6 字符以確保唯一性。

---

### 交易管理架構

```
偽代碼（整體結構）：

conn = None
try:
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False       ← 關閉自動提交，進入手動交易模式
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ... 執行所有業務邏輯（見下方各步驟）
        conn.commit()              ← 全部成功後提交
    
    return (True, booking_dict)

except psycopg2.Error as db_error:
    if conn: conn.rollback()
    return (False, f"Database error: {str(db_error)}")

except Exception as general_error:
    if conn: conn.rollback()
    return (False, f"Booking failed: {str(general_error)}")

finally:
    if conn: conn.close()          ← 無論成功失敗都關閉連線
```

**為何不使用 `_connect()` 的 context manager 模式？**
`_connect()` 使用 `autocommit=True`，寫入操作必須使用 `autocommit=False`。
此函式直接呼叫 `psycopg2.connect(PG_DSN)`，手動管理連線生命週期。

### 業務邏輯步驟（在 try 區塊內）

```
步驟一：驗證使用者存在
  SELECT user_id FROM users WHERE user_id = %s
  fetchone() 為 None → conn.rollback(); return (False, "User {user_id} not found")

步驟二：取得班次資訊（departure_time + base_fare）
  SELECT schedule_id, first_train_time, base_fare_usd
  FROM national_rail_schedules
  WHERE schedule_id = %s
  fetchone() 為 None → conn.rollback(); return (False, "Schedule {schedule_id} not found")

步驟三：計算實際票價
  fare_multipliers = {"standard": 1.0, "first": 1.5, "senior": 0.8, "student": 0.85}
  fare_multiplier = fare_multipliers.get(fare_class, 1.0)
  total_fare_usd = round(float(base_fare_usd) * fare_multiplier, 2)

步驟四：處理座位選擇
  if seat_id == "any":
      available = query_available_seats(schedule_id, travel_date, fare_class)
      ← 注意：此呼叫建立一個新的連線，不影響當前交易
      if not available:
          conn.rollback()
          return (False, "No available seats in {fare_class} class for {schedule_id} on {travel_date}")
      selected_seat = available[0]
      seat_id = selected_seat['seat_id']
      coach = selected_seat['coach']
  else:
      coach = seat_id[0]  ← 從座位 ID 的第一個字元取得車廂（"A05" → "A"）

步驟五：座位衝突偵測（關鍵防護）
  SELECT booking_id FROM national_rail_bookings
  WHERE schedule_id = %s
    AND travel_date = %s::DATE
    AND seat_id = %s
    AND coach = %s
    AND status IN ('pending', 'confirmed')
  FOR UPDATE
  LIMIT 1
  ← FOR UPDATE 是行鎖：防止兩個並發請求同時通過此檢查後各自完成訂票（超賣）
  
  若找到記錄 → conn.rollback()
               return (False, "Seat {seat_id} in coach {coach} is already booked for ...")

步驟六：生成 ID
  booking_id = _gen_booking_id()    ← "BK-" + 6個隨機大寫英數
  payment_id = _gen_payment_id()    ← "PM-" + 6個隨機大寫英數
  （_gen_booking_id() 和 _gen_payment_id() 函式已在 queries.py 頂部定義）

步驟七：插入 national_rail_bookings
  INSERT INTO national_rail_bookings (
      booking_id, user_id, schedule_id, origin_station_id,
      destination_station_id, travel_date, departure_time,
      ticket_type, fare_class, coach, seat_id, amount_usd,
      status, booked_at
  ) VALUES (%s, %s, %s, %s, %s, %s::DATE, %s, %s, %s, %s, %s, %s, %s, NOW())
  ← 共 13 個參數，travel_date 加 ::DATE 轉型

步驟八：插入 payments
  INSERT INTO payments (
      payment_id, booking_id, amount_usd, method, status, paid_at
  ) VALUES (%s, %s, %s, %s, %s, NOW())
  method = 'credit_card'，status = 'paid'

步驟九：提交交易
  conn.commit()
```

### 回傳值組裝

```
成功後回傳：
(True, {
    'booking_id': booking_id,
    'payment_id': payment_id,
    'user_id': user_id,
    'schedule_id': schedule_id,
    'origin_station_id': origin_station_id,
    'destination_station_id': destination_station_id,
    'travel_date': travel_date,
    'departure_time': str(departure_time),       ← timedelta 轉字串
    'ticket_type': ticket_type,
    'fare_class': fare_class,
    'coach': coach,
    'seat_id': seat_id,
    'base_fare_usd': float(base_fare_usd),
    'fare_multiplier': fare_multiplier,
    'total_fare_usd': total_fare_usd,
    'status': 'pending',
    'booked_at': datetime.now(timezone.utc).isoformat()
})
```

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：
1. 正常訂票流程：回傳 `(True, dict)`，dict 包含 `booking_id`（"BK-" 前綴）
2. `seat_id="any"` 時自動選位成功
3. 不存在的 user_id → `(False, "User ... not found")`
4. 不存在的 schedule_id → `(False, "Schedule ... not found")`
5. 座位已被訂 → `(False, "Seat ... is already booked ...")`（衝突偵測有效）
6. 訂票後，重複訂相同座位失敗（原子交易保證）
7. 回傳 dict 的 `status` 為 `"pending"`（非 `"confirmed"`）

**執行測試**：
```bash
pytest tests/unit/ -v -k "execute_booking"
pytest tests/integration/ -v -k "execute_booking"
```
