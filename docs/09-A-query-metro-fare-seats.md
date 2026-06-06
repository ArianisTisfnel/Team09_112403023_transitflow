# 09 — 主軸 A｜捷運票價（依班次+跳數）＋可用座位查詢（JSONB 解析）＋相鄰座位自動選位

> **前置條件**：`05-A-schema-transit-tables.md`（`metro_schedules` 表 + `national_rail_seat_layouts` 表）
> **後續任務**：`10-A-execute-booking.md`（execute_booking 呼叫 query_available_seats）

---

## 任務目標

在 `databases/relational/queries.py` 中實作：
- `query_metro_fare`：以 `schedule_id` 查出班次的 `base_fare_usd` 與 `per_stop_rate_usd`，依 `stops_travelled` 套公式 `total = base + per_stop × stops` 回傳票價
- `query_available_seats`：從 `national_rail_seat_layouts.coaches` JSONB 解析座位佈局，再交叉比對已訂座位
- `auto_select_adjacent_seats`：從 `query_available_seats` 的輸出中選出 `count` 個盡量相鄰的座位

---

## 介面規格

### 函式一：`query_metro_fare`

```python
def query_metro_fare(
    schedule_id: str,
    stops_travelled: int,
) -> Optional[dict]:
```

**票價模型**：`total_fare_usd = base_fare_usd + per_stop_rate_usd × stops_travelled`。
`base_fare_usd` 與 `per_stop_rate_usd` 直接存在 `metro_schedules` 上（來源
`metro_schedules.json`，例：`base 0.80`、`per_stop 0.30`）。

**回傳格式（成功）**：

```json
{
  "schedule_id": "MS_SCH01",
  "stops_travelled": 4,
  "base_fare_usd": 0.80,
  "per_stop_rate_usd": 0.30,
  "total_fare_usd": 2.00
}
```

`schedule_id` 不存在時回傳 `None`。

---

### 函式二：`query_available_seats`

```python
def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
```

**回傳格式**（list，每個元素：）：

```json
{
  "seat_id": "A05",
  "coach": "A",
  "row": 1,
  "column": "A",
  "is_available": true
}
```

排序：`coach ASC, row ASC, column ASC`。
找不到班次、無匹配 fare_class 的 coach，或全部已訂時，回傳 `[]`。

---

### 函式三：`auto_select_adjacent_seats`

```python
def auto_select_adjacent_seats(
    available_seats: list[dict],   # query_available_seats() 的回傳值
    count: int,                    # 需要的座位數
) -> list[str]:                    # 回傳 seat_id 字串 list
```

**選位優先策略**（依序嘗試）：
1. 同一 row 內有 ≥ `count` 個可用座位 → 取該 row 前 `count` 個
2. 找不到 → 依 `(row, column)` 排序取前 `count` 個（跨 row 但行號最接近）

**邊界回傳**：
- `available_seats` 為空，或 `count <= 0` → 回傳 `[]`
- `count >= len(available_seats)` → 回傳所有可用座位的 `seat_id`（最多 `count` 個）

---

## 實作邏輯導引

### query_metro_fare 邏輯步驟

本函式以 `schedule_id` 查出班次費率，再依 `stops_travelled` 套公式定價，不做圖遍歷。

```
偽代碼：

1. 連線 PostgreSQL，查班次費率：
   SELECT base_fare_usd, per_stop_rate_usd
   FROM metro_schedules
   WHERE schedule_id = %s
   參數：(schedule_id,)

2. fetchone()：
   - 若 None → 回傳 None（班次不存在）

3. 套用票價公式：
   base_fare_usd     = float(row['base_fare_usd'])
   per_stop_rate_usd = float(row['per_stop_rate_usd'])
   total_fare_usd    = round(base_fare_usd + per_stop_rate_usd * max(int(stops_travelled), 0), 2)

4. 組裝並回傳 dict：
   return {
       "schedule_id": schedule_id,
       "stops_travelled": stops_travelled,
       "base_fare_usd": base_fare_usd,
       "per_stop_rate_usd": per_stop_rate_usd,
       "total_fare_usd": total_fare_usd,
   }
```

**為什麼從班次讀費率？**
票價依資料驅動：每個班次自帶 `base_fare_usd` 與 `per_stop_rate_usd`，
故總價 = `base + per_stop × stops`，與來源 `metro_schedules.json` 一致，
且能正確反映不同班次的票價差異（而非套用與資料無關的固定級距）。

### query_available_seats 邏輯步驟

```
偽代碼：

1. 連線 PostgreSQL：
   查詢：SELECT layout_id, schedule_id, coaches, total_seats
         FROM national_rail_seat_layouts
         WHERE schedule_id = %s
         
2. 若無結果（layout_row 為 None），回傳 []

3. 解析 coaches JSONB：
   coaches_data = layout_row['coaches']  -- psycopg2 自動將 JSONB 反序列化為 Python list
   all_seats = []
   
   for coach in coaches_data:
       coach_id = coach['coach']          -- "A", "B", "C", "D"
       coach_fare_class = coach['fare_class']  -- "standard" 或 "first"
       
       if coach_fare_class == fare_class:  -- 只處理匹配的 fare_class
           for seat in coach.get('seats', []):
               all_seats.append({
                   'seat_id': seat['seat_id'],
                   'coach': coach_id,
                   'row': seat['row'],
                   'column': seat['column'],
                   'is_available': True     -- 預設可用
               })

4. 若 all_seats 為空，回傳 []

5. 查詢已訂座位：
   SELECT seat_id FROM national_rail_bookings
   WHERE schedule_id = %s
     AND travel_date = %s::DATE
     AND status IN ('confirmed', 'pending')
     AND seat_id IS NOT NULL
   
   booked_seat_ids = {row['seat_id'] for row in fetchall()}  -- Python set，O(1) 查詢

6. 標記不可用座位：
   for seat in all_seats:
       if seat['seat_id'] in booked_seat_ids:
           seat['is_available'] = False

7. 排序：all_seats.sort(key=lambda s: (s['coach'], s['row'], s['column']))

8. 回傳 all_seats
```

**為什麼對 booked_seat_ids 使用 Python set？**
`IN` 查詢的語意是成員檢查，Python `set` 的 `in` 操作是 O(1)，
比每次線性掃描 booked 列表快得多（雖然此場景下效能差異不大，但這是正確的慣用寫法）。

### auto_select_adjacent_seats 邏輯步驟

本函式**不連接資料庫**，純粹在 Python 層對 `query_available_seats` 的輸出進行後處理。

```
偽代碼：

def auto_select_adjacent_seats(available_seats, count):
    # 邊界情況
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]   ← 直接回傳前 count 個

    # 以 row 為 key 分組（available_seats 已按 coach/row/column 排序）
    rows = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    # 優先策略：找第一個有 >= count 個可用座位的 row
    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]   ← 同排優先

    # 退而求其次：按 (row, column) 排序後取前 count 個
    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]
```

**重要說明**：
- 回傳的是 `seat_id` 字串 list，不是完整 dict。
- 輸入的 `available_seats` 應只包含 `is_available=True` 的座位（呼叫方負責過濾，或直接傳入 `query_available_seats` 的完整輸出，本函式不做過濾）。
- 本函式**不快取、不寫入資料庫**，可安全在任何交易上下文外呼叫。
- Stage 3.2 的 `RelationalService` ABC 將此函式宣告為抽象方法；`PostgreSQLService` 直接委派給 `self._q.auto_select_adjacent_seats(*args, **kwargs)`。

---

## 驗收標準

**驗收測試**：

**query_metro_fare 測試驗證**：
1. `total_fare_usd == round(base_fare_usd + per_stop_rate_usd × stops_travelled, 2)`
2. `stops_travelled=0` → 只計 base（`total == base_fare_usd`）
3. 跳數越多總價不減（`per_stop_rate_usd >= 0`）
4. 不存在的 `schedule_id` → 回傳 `None`
5. 成功時回傳 dict 包含 `schedule_id`、`stops_travelled`、`base_fare_usd`、`per_stop_rate_usd`、`total_fare_usd` 欄位

**query_available_seats 測試驗證**：
1. 正確解析 coaches JSONB，只回傳匹配 fare_class 的座位
2. 已訂座位（status='confirmed' 或 'pending'）的 `is_available=False`
3. 已取消座位（status='cancelled'）的 `is_available=True`（不被計入）
4. 結果按 coach、row、column 排序
5. 班次不存在時回傳 `[]`
6. fare_class 無對應 coach 時回傳 `[]`

**auto_select_adjacent_seats 測試驗證**：
1. 空 list 或 count=0 → 回傳 `[]`
2. count > 可用座位數 → 回傳全部座位的 seat_id
3. 同 row 內有足夠座位 → 回傳同 row 座位（不跨 row）
4. 同 row 不夠時 → 跨 row 回傳 (row, column) 最小的前 count 個
5. 回傳值為 `list[str]`（seat_id 字串），非 dict

**執行測試**：
```bash
pytest tests/unit/ -v -k "metro_fare or available_seats"
pytest tests/integration/ -v -k "metro_fare or available_seats"
```
