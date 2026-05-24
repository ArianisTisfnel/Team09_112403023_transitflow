# 11 — 主軸 A｜取消訂票（狀態機驗證 + 稽核軌跡）

> **前置條件**：`10-A-execute-booking.md`（需要已有可取消的訂票資料）
> **後續任務**：`12-A-auth-functions.md`

---

## 任務目標

在 `databases/relational/queries.py` 中實作 `execute_cancellation`，
以原子交易方式取消國鐵訂票，包含狀態機驗證、稽核軌跡記錄、以及退款付款記錄生成。

---

## 介面規格

**目標檔案**：`databases/relational/queries.py`

```python
def execute_cancellation(
    booking_id: str,
    reason: str = "Customer requested",
) -> tuple[bool, dict | str]:
```

**成功回傳**：

```json
(True, {
  "booking_id": "BK-AB123C",
  "original_amount_usd": 15.50,
  "status": "cancelled",
  "cancelled_at": "2025-05-20T10:00:00+00:00",
  "cancellation_reason": "Customer requested",
  "cancellation_timestamp_utc": "2025-05-20T10:00:00+00:00",
  "original_status": "pending"
})
```

**失敗回傳**（各種錯誤情境）：

```python
(False, "Booking BK-XXXXXX not found")
(False, "Cannot cancel booking with status 'completed'. Only 'pending' or 'confirmed' bookings can be cancelled.")
(False, "Cannot cancel booking with status 'cancelled'. Only 'pending' or 'confirmed' bookings can be cancelled.")
(False, "Failed to update booking BK-XXXXXX")
(False, "Database error: ...")
```

---

## 實作邏輯導引

### 狀態機設計

```
允許的轉換路徑：
  pending   → cancelled  ✅
  confirmed → cancelled  ✅
  completed → cancelled  ❌（行程已完成，不允許取消）
  cancelled → cancelled  ❌（重複取消）
```

### 交易管理架構

與 `execute_booking` 相同模式：手動 `autocommit=False` + try/except/finally 結構。

```
偽代碼（整體結構）：

conn = None
try:
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Step 1–4（見下方）
        conn.commit()
    
    return (True, result_dict)

except psycopg2.Error as db_error:
    if conn: conn.rollback()
    return (False, f"Database error: {str(db_error)}")

except Exception as e:
    if conn: conn.rollback()
    return (False, f"Cancellation failed: {str(e)}")

finally:
    if conn: conn.close()
```

### 業務邏輯步驟

```
步驟一：查詢訂票是否存在
  SELECT booking_id, user_id, status, amount_usd, booked_at
  FROM national_rail_bookings
  WHERE booking_id = %s
  
  fetchone() 為 None：
      conn.rollback()
      return (False, "Booking {booking_id} not found")

步驟二：狀態機驗證
  current_status = booking['status']
  if current_status not in ('pending', 'confirmed'):
      conn.rollback()
      return (
          False,
          "Cannot cancel booking with status '{current_status}'. "
          "Only 'pending' or 'confirmed' bookings can be cancelled."
      )

步驟三：更新訂票狀態（三個欄位同時更新）
  cancelled_at_timestamp = datetime.now(timezone.utc)
  
  UPDATE national_rail_bookings
  SET status = 'cancelled',
      cancellation_reason = %s,
      cancelled_at = %s
  WHERE booking_id = %s
  參數：(reason, cancelled_at_timestamp, booking_id)
  
  驗證更新：if cur.rowcount == 0: conn.rollback(); return (False, "Failed to update booking...")

步驟四：在 payments 表新增退款記錄（稽核軌跡）
  payment_id = _gen_payment_id()
  
  INSERT INTO payments (payment_id, booking_id, amount_usd, method, status, paid_at)
  VALUES (%s, %s, %s, %s, %s, NOW())
  參數：(payment_id, booking_id, booking['amount_usd'], 'cancellation', 'refunded')
  
  注意：method = 'cancellation'（非標準支付方式，用於區分退款記錄）
        status = 'refunded'

步驟五：提交交易
  conn.commit()
```

### 回傳值組裝

```
成功後回傳：
(True, {
    'booking_id': booking_id,
    'original_amount_usd': float(booking['amount_usd']),
    'status': 'cancelled',
    'cancelled_at': cancelled_at_timestamp.isoformat(),
    'cancellation_reason': reason,
    'cancellation_timestamp_utc': cancelled_at_timestamp.isoformat(),
    'original_status': current_status    ← 記錄取消前的狀態
})
```

**`cancelled_at` 與 `cancellation_timestamp_utc` 為相同值**，
這是冗餘設計，確保不同的呼叫方可以從不同欄位名取得相同資訊（相容性設計）。

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：
1. 取消 `pending` 狀態訂票成功，回傳 `(True, dict)`
2. 取消 `confirmed` 狀態訂票成功
3. 取消 `completed` 狀態訂票失敗，錯誤訊息包含 `"completed"` 和允許的狀態說明
4. 取消已取消的訂票失敗，錯誤訊息包含 `"cancelled"`
5. 取消後，資料庫中該訂票的 `status` 變為 `"cancelled"`
6. 取消後，`national_rail_bookings.cancelled_at` 欄位有值（非 NULL）
7. 取消後，`national_rail_bookings.cancellation_reason` 欄位有值
8. 取消後，`payments` 表中新增一筆 `status='refunded'` 的記錄
9. 不存在的 booking_id 回傳 `(False, "Booking ... not found")`
10. 回傳 dict 中的 `original_amount_usd` 為 float 型態

**執行測試**：
```bash
pytest tests/unit/ -v -k "execute_cancellation"
pytest tests/integration/ -v -k "execute_cancellation"
```
