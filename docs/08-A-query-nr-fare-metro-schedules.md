# 08 — 主軸 A｜國鐵票價計算（含快取）＋捷運班次查詢（依起訖站）

> **前置條件**：`05-A-schema-transit-tables.md` 完成
> **後續任務**：`09-A-query-metro-fare-seats.md`、`20-B-query-cheapest-route.md`（圖形主軸將呼叫本函式）

---

## 任務目標

在 `databases/relational/queries.py` 中實作：
- `query_national_rail_fare`：以 `schedule_id` 查詢國鐵票價，整合 `fare_cache` 快取
- `query_metro_schedules`：以起訖站 ID 查詢捷運班次，整合 `schedule_cache` 快取

---

## 介面規格

### 函式一：`query_national_rail_fare`

```python
def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
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
  "schedule_id": "NR_SCH01",
  "fare_class": "standard",
  "stops_travelled": 4,
  "base_fare_usd": 12.50,
  "fare_multiplier": 1.0,
  "total_fare_usd": 12.50,
  "currency": "USD"
}
```

`schedule_id` 不存在時回傳 `None`。快取鍵格式：`"fare:{schedule_id}:{fare_class}:{stops_travelled}"`。

---

### 函式二：`query_metro_schedules`

```python
def query_metro_schedules(
    origin_id: str,
    destination_id: str,
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
  "operating_days": ["Mon","Tue","Wed","Thu","Fri"]
}
```

無匹配班次時回傳 `[]`。快取鍵格式：`"metro_sched:{origin_id}:{destination_id}"`。

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
   # cache_key = f"fare:{schedule_id}:{fare_class}:{stops_travelled}"

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
   WHERE schedule_id = %s
   參數：(schedule_id,)

5. fetchone()：
   - 若 None → 回傳 None（不寫快取）

6. 計算票價：
   base_fare_usd = float(result['base_fare_usd'])
   total_fare_usd = round(base_fare_usd * fare_multiplier, 2)

7. 組裝回傳 dict，寫入快取（Stage 3.3 補入，此階段略過）：
   fare_result = {
       "schedule_id": schedule_id,
       "fare_class": fare_class,
       "stops_travelled": stops_travelled,
       "base_fare_usd": base_fare_usd,
       "fare_multiplier": fare_multiplier,
       "total_fare_usd": total_fare_usd,
       "currency": "USD",
   }
   # fare_cache.set(cache_key, fare_result)
   return fare_result
```

**為什麼快取只寫在「找到結果」的情況下？**
None 結果表示該班次不存在，資料庫可能稍後補齊，不應永久快取。

**為什麼 `stops_travelled` 包含在回傳 dict 但不用於票價計算？**
`national_rail_schedules` 只有 `base_fare_usd`（整段路線票價），
`stops_travelled` 由呼叫方傳入並原樣回傳，供 agent 組裝回答時使用。
快取鍵包含 `stops_travelled` 確保不同跳數的查詢結果彼此獨立。

### query_metro_schedules 邏輯步驟

本函式以起訖站 ID 直接查詢班次，不需篩選線路、方向或日期：

```
偽代碼（Stage 1/2 暫無快取版本）：

1. 組合快取鍵、查詢快取（Stage 3.3 補入，此階段略過）：
   # cache_key = f"metro_sched:{origin_id}:{destination_id}"
   # cached = schedule_cache.get(cache_key)
   # if cached is not None: return cached

2. 連線 PostgreSQL，查詢：
   SELECT
       schedule_id, line, direction,
       origin_station_id, destination_station_id,
       TO_CHAR(first_train_time, 'HH24:MI') AS first_train_time,
       TO_CHAR(last_train_time, 'HH24:MI') AS last_train_time,
       base_fare_usd, operating_days
   FROM metro_schedules
   WHERE origin_station_id = %s AND destination_station_id = %s
   參數：(origin_id, destination_id)

3. fetchall()，轉 list[dict]，寫入快取（Stage 3.3 補入，此階段略過）並回傳：
   # schedule_cache.set(cache_key, result)
   return result
```

**關鍵點：`TO_CHAR` 時間格式化**
PostgreSQL 的 `TIME` 欄位在 Python 中預設被 psycopg2 轉為 `datetime.timedelta` 物件，
測試期待的是 `"HH:MM"` 字串，因此必須在 SQL 中使用 `TO_CHAR(col, 'HH24:MI')` 轉換。

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：

`query_national_rail_fare`：
1. 標準票（fare_class="standard"）回傳 `total_fare_usd = base_fare_usd * 1.0`
2. 頭等票（fare_class="first"）回傳 `total_fare_usd = base_fare_usd * 1.5`
3. `schedule_id` 不存在時回傳 `None`
4. 無效 fare_class 時使用 1.0 乘數
5. 回傳 dict 包含 `schedule_id`、`stops_travelled`、`base_fare_usd`、`total_fare_usd`、`currency` 欄位
6. ⏩ **（Stage 3.3 補入，此處暫不驗）** 第二次呼叫相同參數時從快取取得——此行為由 `25-stage3.3-performance-boost.md` 的 `performance_boost` 測試覆蓋，Stage 1/2 的 `-k "national_rail_fare"` 測試**不驗證**快取命中

`query_metro_schedules`：
1. 指定 origin_id / destination_id，回傳連結這兩站的班次
2. 不存在的起訖站組合回傳 `[]`
3. 時間欄位為字串格式（`"06:00"` 而非 timedelta）
4. 回傳 dict 包含 `schedule_id`、`line`、`direction`、`base_fare_usd`、`operating_days` 欄位
5. ⏩ **（Stage 3.3 補入，此處暫不驗）** 第二次呼叫相同參數時從快取取得——同上，由 `performance_boost` 測試覆蓋

**執行測試**：
```bash
pytest tests/unit/ -v -k "national_rail_fare or metro_schedules"
```
