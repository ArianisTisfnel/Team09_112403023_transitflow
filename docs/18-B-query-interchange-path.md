# 18 — 主軸 B｜跨網路換乘路徑 + 換乘可行性驗證

> **前置條件**：`15-B-neo4j-seed-interchange.md` 完成（INTERCHANGE 關係已建立）
> **後續任務**：`19-B-query-delay-ripple.md`

---

## 任務目標

在 `databases/graph/queries.py` 中實作兩個緊密相關的函式：
- `query_interchange_path`：找從起點到終點的路線，但**必須包含至少一個 INTERCHANGE 換乘關係**
- `validate_interchange_feasibility`：驗證路徑中每個換乘點的步行時間是否 >= 15 分鐘

---

## 介面規格

### 函式一：`query_interchange_path`

```python
def query_interchange_path(origin_id: str, destination_id: str) -> dict:
```

**成功回傳**：

```json
{
  "found": true,
  "origin_id": "MS01",
  "destination_id": "NR05",
  "station_ids": ["MS01", "NR01", "NR03", "NR05"],
  "stations": [...],
  "interchange_points": [
    {
      "from_station_id": "MS01",
      "from_station_name": "Central Square",
      "from_network": "metro",
      "to_station_id": "NR01",
      "to_station_name": "Central Station",
      "to_network": "national_rail"
    }
  ],
  "total_travel_time_min": 55,
  "num_legs": 3,
  "legs": [
    {
      "from_station_id": "MS01",
      "from_station_name": "Central Square",
      "to_station_id": "NR01",
      "to_station_name": "Central Station",
      "from_network": "metro",
      "to_network": "national_rail",
      "relationship_type": "INTERCHANGE",
      "travel_time_min": 15
    },
    ...
  ]
}
```

**無換乘路徑時回傳**：

```json
{
  "found": false,
  "origin_id": "MS01",
  "destination_id": "MS09",
  "station_ids": [], "stations": [],
  "interchange_points": [],
  "total_travel_time_min": 0,
  "legs": [],
  "error": "No interchange path found from MS01 to MS09"
}
```

---

### 函式二：`validate_interchange_feasibility`

```python
def validate_interchange_feasibility(path_details: dict) -> bool:
```

**輸入**：任意包含 `legs` 或 `interchange_points` 的路徑 dict（通常為 `query_interchange_path` 的回傳值）

**回傳**：`True`（所有換乘 >= 15 分鐘）或 `False`（至少一個換乘 < 15 分鐘）

**支援兩種資料佈局**：
- **Layout A**（`legs` 清單）：每個 leg 有 `relationship_type` 和 `travel_time_min`
- **Layout B**（`interchange_points` 清單）：每個點有可選的 `arrival_time`、`departure_time` 或 `transfer_time_min`

---

## 實作邏輯導引

### query_interchange_path 的兩段式 Cypher 策略

本函式需要同時提取：路徑節點序列、關係類型、換乘點資訊。
由於 APOC 的 path 物件在 Python 端解析複雜，採用**兩段式查詢**：

**第一段：找路徑**

```
Cypher：

MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})

CALL apoc.algo.allSimplePaths(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',
    10                               ← 深度 10，允許跨網路的較長路徑
) YIELD path

WHERE length(path) > 0
    AND any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')
    ← 過濾條件：路徑中必須有至少一條 INTERCHANGE 關係

RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations,
    [rel IN relationships(path) | rel.travel_time_min] AS travel_times

LIMIT 1   ← 只取第一條符合條件的換乘路徑
```

**第二段：取關係細節**（用於建構 legs 和標記換乘點）

```
Cypher：

MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})

CALL apoc.algo.allSimplePaths(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',
    10
) YIELD path

WHERE length(path) > 0
    AND any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')

UNWIND relationships(path) AS rel
WITH path, rel,
     startNode(rel) AS from_node,
     endNode(rel) AS to_node,
     type(rel) AS rel_type

RETURN
    from_node.station_id  AS from_id,
    from_node.name        AS from_name,
    from_node.network_type AS from_network,
    to_node.station_id    AS to_id,
    to_node.name          AS to_name,
    to_node.network_type  AS to_network,
    rel_type,
    rel.travel_time_min   AS travel_time

LIMIT 20
```

### Python 層整合邏輯

```
偽代碼：

def query_interchange_path(origin_id, destination_id):
    try:
        with get_pool() as driver:
            with driver.session() as session:
                # 第一段：取節點序列
                result1 = session.run(<<第一段 Cypher>>, origin_id=..., destination_id=...)
                record = result1.single()
                
                if not record:
                    return {found: False, ..., error: "No interchange path found from ..."}
                
                station_ids = record["station_ids"]
                stations = record["stations"]
                travel_times = record["travel_times"]
                
                # 計算總時間
                total_time = sum(t for t in travel_times if t is not None)
                
                # 第二段：取關係細節
                result2 = session.run(<<第二段 Cypher>>, origin_id=..., destination_id=...)
                rel_records = result2.fetch(20)
                
                # 建立 (from_id, to_id) → leg_dict 的映射
                legs_map = {}
                interchange_points = []
                
                for rel_record in rel_records:
                    key = (rel_record["from_id"], rel_record["to_id"])
                    legs_map[key] = {
                        "from_station_id": rel_record["from_id"],
                        "from_station_name": rel_record["from_name"],
                        "to_station_id": rel_record["to_id"],
                        "to_station_name": rel_record["to_name"],
                        "from_network": rel_record["from_network"],
                        "to_network": rel_record["to_network"],
                        "relationship_type": rel_record["rel_type"],
                        "travel_time_min": rel_record["travel_time"] or 0,
                    }
                    
                    # 標記換乘點
                    if rel_record["rel_type"] == "INTERCHANGE":
                        interchange_points.append({...})
                
                # 按 station_ids 順序組裝 legs
                legs = []
                for i in range(len(station_ids) - 1):
                    key = (station_ids[i], station_ids[i + 1])
                    if key in legs_map:
                        legs.append(legs_map[key])
                    else:
                        # Fallback：使用 stations 陣列建構
                        legs.append({..., "relationship_type": "UNKNOWN", "travel_time_min": 0})
                
                return {
                    "found": True,
                    "station_ids": station_ids,
                    "stations": stations,
                    "interchange_points": interchange_points,
                    "total_travel_time_min": int(total_time),
                    "num_legs": len(legs),
                    "legs": legs,
                }
    
    except Exception as e:
        return {found: False, ..., error: f"Error querying interchange path: {str(e)}"}
```

### validate_interchange_feasibility 邏輯

```
偽代碼：

def validate_interchange_feasibility(path_details):
    MIN_TRANSFER = 15
    
    # Layout A：檢查 legs 中的 INTERCHANGE 腿
    for leg in path_details.get("legs", []):
        if leg.get("relationship_type") == "INTERCHANGE":
            if (leg.get("travel_time_min") or 0) < MIN_TRANSFER:
                return False
    
    # Layout B：檢查 interchange_points
    for point in path_details.get("interchange_points", []):
        arrival = point.get("arrival_time")
        departure = point.get("departure_time")
        
        if arrival and departure:
            # 解析時間字串計算分鐘差
            try:
                fmt = "%H:%M:%S" if len(str(arrival)) > 5 else "%H:%M"
                arr_dt = datetime.strptime(str(arrival), fmt)
                dep_dt = datetime.strptime(str(departure), fmt)
                if dep_dt < arr_dt:
                    dep_dt += timedelta(days=1)  ← 跨午夜補正
                diff_min = int((dep_dt - arr_dt).total_seconds()) // 60
                if diff_min < MIN_TRANSFER:
                    return False
            except (ValueError, TypeError):
                transfer_min = point.get("transfer_time_min") or 0
                if transfer_min < MIN_TRANSFER:
                    return False
        
        elif "transfer_time_min" in point:
            if (point.get("transfer_time_min") or 0) < MIN_TRANSFER:
                return False
    
    return True  ← 所有換乘都通過驗證
```

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：

`query_interchange_path`：
1. 跨網路查詢（MS01 → NR05）回傳 `found=True`，`interchange_points` 非空
2. 同網路查詢（MS01 → MS09，無需換乘）回傳 `found=False`（找不到含 INTERCHANGE 的路徑）
3. `interchange_points` 中每個點有 `from_network` 和 `to_network` 欄位
4. `legs` 中的 INTERCHANGE 腿有 `travel_time_min=15`

`validate_interchange_feasibility`：
1. `travel_time_min=15` 的 INTERCHANGE 腿 → `True`（等於閾值，可行）
2. `travel_time_min=14` 的 INTERCHANGE 腿 → `False`（低於閾值，不可行）
3. 無 INTERCHANGE 腿的路徑 → `True`（不需驗證）
4. `arrival_time` + `departure_time` 差距 >= 15 分鐘 → `True`

**執行測試**：
```bash
pytest tests/unit/ -v -k "interchange_path or interchange_feasibility"
pytest tests/integration/ -v -k "interchange_path"
```
