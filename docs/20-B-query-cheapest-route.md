# 20 — 主軸 B｜最低票價路線（allSimplePaths + 跨模組票價計算）

> **前置條件**：
>   - `15-B-neo4j-seed-interchange.md` 完成（圖拓撲完整）
>   - `08-A-query-nr-fare-metro-schedules.md` 完成（`query_national_rail_fare` 可呼叫）
>   - `09-A-query-metro-fare-seats.md` 完成（`query_metro_fare` 可呼叫）
> **後續任務**：無（B 主軸最終任務）

---

## 任務目標

在 `databases/graph/queries.py` 中實作 `query_cheapest_route`，
枚舉所有簡單路徑，對每條路徑的每個路段呼叫對應的票價函式，
計算總費用後排序，回傳最便宜的 3 條路線。

---

## 介面規格

**目標檔案**：`databases/graph/queries.py`

```python
def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
```

**成功回傳**：

```json
{
  "found": true,
  "origin_id": "NR01",
  "destination_id": "NR05",
  "cheapest_routes": [
    {
      "station_ids": ["NR01", "NR02", "NR03", "NR05"],
      "stations": [...],
      "total_fare_usd": 12.50,
      "legs": [
        {
          "from_station_id": "NR01",
          "from_station_name": "Central Station",
          "to_station_id": "NR02",
          "to_station_name": "Riverside Rail",
          "segment_fare_usd": 6.25
        },
        ...
      ]
    }
  ],
  "routes_found_total": 5,
  "num_cheapest": 3
}
```

**無路徑時回傳**：

```json
{
  "found": false,
  "origin_id": "NR01",
  "destination_id": "INVALID",
  "cheapest_routes": [],
  "error": "No path found from NR01 to INVALID"
}
```

---

## 實作邏輯導引

### 整體算法設計

```
偽代碼（高層次）：

1. 使用 apoc.algo.allSimplePaths 枚舉所有路徑（max_hops=5）
2. 對每條路徑：
   a. 遍歷每個路段（相鄰站點對）
   b. 根據路段的站點類型（捷運 or 國鐵）呼叫對應的票價函式
   c. 累加路段票價 → total_fare_usd
3. 按 total_fare_usd 排序所有路徑
4. 回傳前 3 條最便宜的路徑
```

### 第一步：枚舉所有路徑

```
Cypher：

MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})

CALL apoc.algo.allSimplePaths(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',
    5
) YIELD path

WHERE length(path) > 0

RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations

LIMIT 10   ← 最多評估 10 條路徑（效能限制）
```

### 第二步：跨模組票價計算

```
偽代碼（票價計算邏輯）：

# 在 Python 層 import 另一個模組的函式（跨模組呼叫）
from databases.relational.queries import query_national_rail_fare, query_metro_fare

for path_record in paths:
    station_ids = path_record["station_ids"]
    stations = path_record["stations"]
    
    total_fare_usd = 0.0
    segment_fares = []
    
    for i in range(len(station_ids) - 1):
        from_id = station_ids[i]
        to_id = station_ids[i + 1]
        from_station = stations[i]
        to_station = stations[i + 1]
        
        # 根據站點 ID 前綴判斷網路類型
        is_from_metro = from_id.startswith("MS")
        is_to_metro = to_id.startswith("MS")
        
        try:
            if is_from_metro and is_to_metro:
                # 捷運路段：呼叫 query_metro_fare（BFS 計算）
                fare_info = query_metro_fare(from_id, to_id)
                segment_fare = fare_info.get("fare_usd", 0.0) or 0.0
            else:
                # 國鐵路段（或跨網路路段）：呼叫 query_national_rail_fare
                fare_info = query_national_rail_fare(from_id, to_id, fare_class)
                if fare_info:
                    segment_fare = fare_info.get("total_fare_usd", 0.0)
                else:
                    segment_fare = 5.0  ← 找不到票價時的預設值（兜底邏輯）
            
            total_fare_usd += segment_fare
            segment_fares.append({
                "from_station_id": from_id,
                "from_station_name": from_station["name"],
                "to_station_id": to_id,
                "to_station_name": to_station["name"],
                "segment_fare_usd": segment_fare,
            })
        
        except Exception as e:
            # 票價計算失敗（如資料庫連線問題），使用預設票價繼續
            segment_fare = 5.0
            total_fare_usd += segment_fare
            segment_fares.append({..., "segment_fare_usd": segment_fare})
    
    costed_paths.append({
        "station_ids": station_ids,
        "stations": stations,
        "total_fare_usd": round(total_fare_usd, 2),
        "legs": segment_fares,
    })
```

### 第三步：排序並回傳

```
# 按 total_fare_usd 由低到高排序
sorted_paths = sorted(costed_paths, key=lambda x: x["total_fare_usd"])
cheapest_routes = sorted_paths[:3]

return {
    "found": True,
    "origin_id": origin_id,
    "destination_id": destination_id,
    "cheapest_routes": cheapest_routes,
    "routes_found_total": len(costed_paths),
    "num_cheapest": len(cheapest_routes),
}
```

### 設計考量：INTERCHANGE 路段的票價

捷運 → 國鐵的換乘段（INTERCHANGE 關係）本身沒有票價（它是步行換乘，不是乘車段）。
但在路徑枚舉中，INTERCHANGE 端點是兩個不同站點，計算票價時：
- `from_id` 可能是 `MS01`（捷運）
- `to_id` 可能是 `NR01`（國鐵）
- `query_national_rail_fare("MS01", "NR01", ...)` 可能回傳 None（因為 MS01 不在國鐵時刻表中）

這種情況下的兜底邏輯（預設 `segment_fare = 5.0`）確保計算不中斷，
但結果是近似的，呼叫方應理解這是估算而非精確票價。

---

## 驗收標準

**驗收測試**：

**手動驗收**：
```python
from databases.graph.queries import query_cheapest_route
result = query_cheapest_route("NR01", "NR05", fare_class="standard")
print(result["found"])                    # True
print(len(result["cheapest_routes"]))     # 1–3
print(result["cheapest_routes"][0]["total_fare_usd"])  # > 0
# 確認路線按票價排序
fares = [r["total_fare_usd"] for r in result["cheapest_routes"]]
assert fares == sorted(fares)  # 由低到高排序
```

**通過條件**：
1. 回傳最多 3 條路線，按 `total_fare_usd` 由低到高排序
2. 每條路線有 `legs` 陣列，每個 leg 有 `segment_fare_usd`
3. 無路徑時回傳 `found=False`（不拋出例外）
4. 任何例外時也回傳 `found=False`（不向上傳播）
5. `routes_found_total >= num_cheapest`（找到的路線數 >= 回傳的最佳路線數）

**執行測試**：
```bash
pytest tests/integration/test_phase_2.5_gap_fill_integration.py -v -k "cheapest_route"
```

> ℹ️ **整合測試說明**：`query_cheapest_route` 的整合測試位於
> `tests/integration/test_phase_2.5_gap_fill_integration.py`（`TestQueryCheapestRouteIntegration`）。
> 使用 NR01 → NR05（國鐵同網路路線）作為主要測試情境，
> 涵蓋：`found=True`、路線按票價升序排序、每條路線有 `legs` 且 `total_fare_usd > 0`。
>
> 舊版文件中的 `pytest tests/integration/ -v -k "cheapest_route"` 會收集到 **0 筆測試**
>（整合測試目錄中無任何檔案或函式含有 "cheapest_route" 關鍵字），請使用上方修正後的命令。
