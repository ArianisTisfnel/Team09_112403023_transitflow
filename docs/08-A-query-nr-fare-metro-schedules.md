# 08 — 主軸 A｜國鐵票價計算（含快取）＋捷運班次查詢（含 JSONB 營運日）

> **前置條件**：`05-A-schema-transit-tables.md` 完成
> **後續任務**：`09-A-query-metro-fare-seats.md`、`20-B-query-cheapest-route.md`（圖形主軸將呼叫本函式）

---

## 任務目標

在 `databases/relational/queries.py` 中實作：
- `query_national_rail_fare`：計算國鐵票價，整合 `fare_cache` 快取
- `query_metro_schedules`：查詢捷運班次，整合 `schedule_cache` 快取，支援 JSONB 營運日過濾

---

## 介面規格

### 函式一：`query_national_rail_fare`

```python
def query_national_rail_fare(
    origin_id: str,
    destination_id: str,
    fare_class: str = "standard",
) -> Optional[dict]:
```

**票價乘數對照表**：

| fare_class | 乘數 |
|---|---|
| `"standard"` | `1.0` |
| `"first"` | `1.5` |
| `"senior"` | `0.8` |
| `"student"` | `0.85` |
| （其他值） | `1.0`（預設） |

**回傳格式**：

```json
{
  "origin_id": "NR01",
  "destination_id": "NR05",
  "fare_class": "standard",
  "base_fare_usd": 12.50,
  "fare_multiplier": 1.0,
  "total_fare_usd": 12.50,
  "currency": "USD"
}
```

路線不存在時回傳 `None`。快取鍵格式：`"fare:{origin_id}:{destination_id}:{fare_class}"`。

---

### 函式二：`query_metro_schedules`

```python
def query_metro_schedules(
    line_id: str,
    direction: Optional[str] = None,
    travel_date: Optional[str] = None,
) -> list[dict]:
```

**回傳格式**（list，每個元素：）：

```json
{
  "schedule_id": "M1_SCH01",
  "line": "M1",
  "direction": "northbound",
  "origin_station_id": "MS01",
  "destination_station_id": "MS10",
  "first_train_time": "06:00",
  "last_train_time": "23:30",
  "base_fare_usd": 1.50,
  "operating_days": ["Mon","Tue","Wed","Thu","Fri"],
  "travel_date": "2025-06-01"
}
```

無匹配班次時回傳 `[]`。快取鍵格式：`"metro_sched:{line_id}:{direction或'all'}:{travel_date或'today'}"`。

---

## 實作邏輯導引

> ⚠️ **Stage 1/2 實作注意（快取整合順序）**：`skeleton/cache.py` 在 Stage 3.3 才建立。
> Stage 1/2 階段**暫時跳過快取邏輯**，直接查 DB 並回傳結果即可——`queries.py` 頂部**不要**寫 `from skeleton.cache import ...`，函式本體也不要有任何 `fare_cache` / `schedule_cache` 呼叫。
> 完成 Stage 3.3（`25-stage3.3-performance-boost.md`）後，再依 doc 25 的偽代碼回頭補入快取整合；
> Stage 1/2 的驗收測試（`pytest tests/unit/ -v -k "national_rail_fare or metro_schedules"`）在無快取的情況下應可全部通過。

### query_national_rail_fare 邏輯步驟

```
偽代碼（Stage 1/2 暫無快取版本）：

1. 組合快取鍵（Stage 3.3 補入，此階段略過）：
   # cache_key = f"fare:{origin_id}:{destination_id}:{fare_class}"

2. 查詢快取（Stage 3.3 補入，此階段略過）：
   # cached = fare_cache.get(cache_key)
   # if cached is not None:
   #     return cached  -- 快取命中，直接回傳

3. 定義乘數字典：
   FARE_MULTIPLIERS = {"standard": 1.0, "first": 1.5, "senior": 0.8, "student": 0.85}
   fare_multiplier = FARE_MULTIPLIERS.get(fare_class, 1.0)  -- 無效值預設 1.0

4. 連線 PostgreSQL，查詢：
   SELECT base_fare_usd
   FROM national_rail_schedules
   WHERE origin_station_id = %s AND destination_station_id = %s
   LIMIT 1
   參數：(origin_id, destination_id)

5. fetchone()：
   - 若 None → 回傳 None（不寫快取）

6. 計算票價：
   base_fare_usd = float(result['base_fare_usd'])
   total_fare_usd = round(base_fare_usd * fare_multiplier, 2)

7. 組裝回傳 dict，寫入快取（Stage 3.3 補入，此階段略過）：
   # fare_cache.set(cache_key, fare_result)
   return fare_result
```

**為什麼快取只寫在「找到結果」的情況下？**
None 結果表示該路線不存在，資料庫可能稍後補齊，不應永久快取。

### query_metro_schedules 邏輯步驟

本函式需根據 `direction` 和 `travel_date` 的組合，執行四種不同的 SQL 查詢：

```
偽代碼（Stage 1/2 暫無快取版本）：

1. 組合快取鍵、查詢快取（Stage 3.3 補入，此階段略過）：
   # cache_key = f"metro_sched:{line_id}:{direction or 'all'}:{travel_date or 'today'}"
   # cached = schedule_cache.get(cache_key)
   # if cached is not None: return cached

2. 根據參數組合選擇 SQL 分支：
   - 有 travel_date + 有 direction → 三個 WHERE 條件（line + direction + operating_days）
   - 有 travel_date + 無 direction → 兩個 WHERE 條件（line + operating_days）
   - 無 travel_date + 有 direction → 用 CURRENT_DATE 的 Dy 縮寫過濾
   - 無 travel_date + 無 direction → 用 CURRENT_DATE，只過濾 line

3. 所有分支的 operating_days 過濾邏輯（JSONB 包含運算子）：
   WHERE operating_days @> jsonb_build_array(TO_CHAR($travel_date::DATE, 'Dy'))
   -- 'Dy' 格式化為三字母縮寫：'Mon','Tue','Wed','Thu','Fri','Sat','Sun'
   -- @> 是 JSONB 的「包含」運算子：左邊 JSONB 陣列是否包含右邊的所有元素

4. 時間欄位格式化：
   TO_CHAR(first_train_time, 'HH24:MI') AS first_train_time
   TO_CHAR(last_train_time, 'HH24:MI') AS last_train_time
   -- 確保回傳字串而非 Python timedelta 物件

5. fetchall()，轉 list[dict]，寫入快取（Stage 3.3 補入，此階段略過）並回傳：
   # schedule_cache.set(cache_key, result)
   return result
```

**關鍵點：`TO_CHAR` 時間格式化**
PostgreSQL 的 `TIME` 欄位在 Python 中預設被 psycopg2 轉為 `datetime.timedelta` 物件，
測試期待的是 `"HH:MM"` 字串，因此必須在 SQL 中使用 `TO_CHAR(col, 'HH24:MI')` 轉換。

**關鍵點：`Dy` 縮寫的大小寫**
`TO_CHAR(date, 'Dy')` 回傳首字大寫（`Mon`），若資料中存的是 `Mon`，則比對成功。
確認種子資料（seed_postgres.py）使用的星期縮寫格式與此一致。

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：

`query_national_rail_fare`：
1. 標準票（fare_class="standard"）回傳 `total_fare_usd = base_fare_usd`
2. 頭等票（fare_class="first"）回傳 `total_fare_usd = base_fare_usd * 1.5`
3. 路線不存在時回傳 `None`
4. 無效 fare_class 時使用 1.0 乘數
5. ⏩ **（Stage 3.3 補入，此處暫不驗）** 第二次呼叫相同參數時從快取取得——此行為由 `25-stage3.3-performance-boost.md` 的 `performance_boost` 測試覆蓋，Stage 1/2 的 `-k "national_rail_fare"` 測試**不驗證**快取命中

`query_metro_schedules`：
1. 指定 line_id 回傳該線路的班次
2. 指定 travel_date 時，非營運日（如平日線路在假日）回傳 `[]`
3. 指定 direction 時只回傳該方向班次
4. 時間欄位為字串格式（`"06:00"` 而非 timedelta）
5. ⏩ **（Stage 3.3 補入，此處暫不驗）** 第二次呼叫相同參數時從快取取得——同上，由 `performance_boost` 測試覆蓋

**執行測試**：
```bash
pytest tests/unit/ -v -k "national_rail_fare or metro_schedules"
```
