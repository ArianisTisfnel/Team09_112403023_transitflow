# 19 — 主軸 B｜延誤漣漪分析（BFS 主次影響區分類）

> **前置條件**：`15-B-neo4j-seed-interchange.md` 完成
> **後續任務**：`20-B-query-cheapest-route.md`

---

## 任務目標

在 `databases/graph/queries.py` 中實作 `query_delay_ripple`，
使用可變長度路徑（BFS 原理）找出在指定站點發生延誤時，
所有受波及的站點，並依距離分類為「主要影響區」（1 跳）和「次要影響區」（2+ 跳）。

---

## 介面規格

**目標檔案**：`databases/graph/queries.py`

```python
def query_delay_ripple(affected_station_id: str, hops: int = 2) -> dict:
```

**成功回傳**：

```json
{
  "affected_station_id": "NR03",
  "affected_station": {
    "station_id": "NR03",
    "name": "Old Town Halt",
    "network_type": "national_rail"
  },
  "primary_impact_zone": [
    {
      "station_id": "NR02",
      "name": "Riverside Rail",
      "network_type": "national_rail",
      "lines": ["NR1"],
      "hops_away": 1
    }
  ],
  "secondary_impact_zone": [
    {
      "station_id": "NR01",
      "name": "Central Station",
      "network_type": "national_rail",
      "lines": ["NR1"],
      "hops_away": 2
    }
  ],
  "total_affected_stations": 6,
  "total_hops_searched": 2
}
```

**站點不存在時回傳**：

```json
{
  "affected_station_id": "INVALID",
  "affected_station": null,
  "primary_impact_zone": [],
  "secondary_impact_zone": [],
  "total_affected_stations": 0,
  "total_hops_searched": 2,
  "error": "Affected station INVALID not found"
}
```

**任何例外時**：`error` 欄位填入錯誤訊息，其他欄位為空值。

---

## 實作邏輯導引

### 三段式查詢策略

本函式需要：
1. 確認中心站點存在
2. 找出所有在 N 跳範圍內的站點
3. 對每個站點計算其與中心的精確距離

這需要三段 Cypher 查詢：

**第一段：查詢中心站點**

```
Cypher：

MATCH (center:Station {station_id: $station_id})
RETURN center.station_id AS station_id,
       center.name AS name,
       center.network_type AS network_type
```

若 `result.single()` 為 None → 回傳站點不存在的錯誤結構。

**第二段：找出所有在 N 跳內的鄰居**

```
Cypher（注意：hops 必須嵌入字串，不能用參數）：

MATCH (center:Station {{station_id: $affected_station_id}})
MATCH (center)-[*1..{hops}]-(neighbor:Station)
WHERE neighbor.station_id <> center.station_id
RETURN DISTINCT neighbor.station_id AS station_id,
       neighbor.name AS name,
       neighbor.network_type AS network_type,
       neighbor.lines AS lines
```

**為什麼 `{hops}` 是 Python f-string 而非 Cypher 參數？**
Neo4j 不允許在可變長度路徑模式 `[*1..N]` 中使用 Cypher 參數（`$hops`）。
這是 Cypher 語言的限制，必須用字串插值將整數直接嵌入查詢字串。

**重要的安全注意事項**：
`hops` 是整數參數，在嵌入前驗證型態（`int(hops)`）可防止注入風險。
若 `hops` 是使用者輸入，需在 Python 層限制其範圍（如 `1 <= hops <= 5`）。

**第三段：計算每個鄰居的精確距離**

```
Cypher（同樣需要 f-string 嵌入 hops）：

MATCH (center:Station {{station_id: $affected_station_id}})
MATCH (neighbor:Station {{station_id: $neighbor_id}})
MATCH path = shortestPath((center)-[*1..{hops}]-(neighbor))
WHERE center.station_id <> neighbor.station_id
RETURN length(path) AS hop_count
```

對第二段查詢到的每個鄰居，各執行一次第三段查詢取得精確跳數。

### Python 層整合邏輯

```
偽代碼：

def query_delay_ripple(affected_station_id, hops=2):
    try:
        with get_pool() as driver:
            with driver.session() as session:
                # 第一段：確認中心站點
                center_result = session.run(<<第一段>>, station_id=affected_station_id)
                center_record = center_result.single()
                
                if not center_record:
                    return {affected_station_id: ..., affected_station: None,
                            primary_impact_zone: [], secondary_impact_zone: [],
                            total_affected_stations: 0, total_hops_searched: hops,
                            error: f"Affected station {affected_station_id} not found"}
                
                affected_station = {
                    "station_id": center_record["station_id"],
                    "name": center_record["name"],
                    "network_type": center_record["network_type"]
                }
                
                # 第二段：取得所有鄰居
                ripple_query = f"""
                MATCH (center:Station {{station_id: $affected_station_id}})
                MATCH (center)-[*1..{hops}]-(neighbor:Station)
                WHERE neighbor.station_id <> center.station_id
                RETURN DISTINCT neighbor.station_id AS station_id,
                       neighbor.name AS name,
                       neighbor.network_type AS network_type,
                       neighbor.lines AS lines
                """
                
                neighbors_result = session.run(ripple_query, affected_station_id=affected_station_id)
                neighbors_records = neighbors_result.fetch(100)
                
                if not neighbors_records:
                    return {..., primary_impact_zone: [], secondary_impact_zone: [],
                            total_affected_stations: 0, total_hops_searched: hops}
                
                # 第三段：對每個鄰居計算精確距離，分類
                primary_impact_zone = []
                secondary_impact_zone = []
                seen_stations = set()
                
                distance_query = f"""
                MATCH (center:Station {{station_id: $affected_station_id}})
                MATCH (neighbor:Station {{station_id: $neighbor_id}})
                MATCH path = shortestPath((center)-[*1..{hops}]-(neighbor))
                WHERE center.station_id <> neighbor.station_id
                RETURN length(path) AS hop_count
                """
                
                for neighbor_record in neighbors_records:
                    neighbor_id = neighbor_record["station_id"]
                    if neighbor_id in seen_stations:
                        continue
                    seen_stations.add(neighbor_id)
                    
                    distance_result = session.run(distance_query,
                        affected_station_id=affected_station_id,
                        neighbor_id=neighbor_id)
                    distance_record = distance_result.single()
                    hop_count = distance_record["hop_count"] if distance_record else hops
                    
                    station_info = {
                        "station_id": neighbor_record["station_id"],
                        "name": neighbor_record["name"],
                        "network_type": neighbor_record["network_type"],
                        "lines": neighbor_record["lines"],
                        "hops_away": hop_count,
                    }
                    
                    if hop_count == 1:
                        primary_impact_zone.append(station_info)
                    else:  # hop_count >= 2
                        secondary_impact_zone.append(station_info)
                
                # 排序（確保輸出一致）
                primary_impact_zone.sort(key=lambda x: x["station_id"])
                secondary_impact_zone.sort(key=lambda x: x["station_id"])
                
                return {
                    "affected_station_id": affected_station_id,
                    "affected_station": affected_station,
                    "primary_impact_zone": primary_impact_zone,
                    "secondary_impact_zone": secondary_impact_zone,
                    "total_affected_stations": len(primary_impact_zone) + len(secondary_impact_zone),
                    "total_hops_searched": hops,
                }
    
    except Exception as e:
        return {affected_station_id: ..., error: f"Error querying delay ripple: {str(e)}",
                primary_impact_zone: [], secondary_impact_zone: [],
                total_affected_stations: 0, total_hops_searched: hops}
```

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：
1. `NR03` 受影響時，直連站（1 跳）出現在 `primary_impact_zone`
2. 間接連接站（2 跳）出現在 `secondary_impact_zone`
3. `total_affected_stations = len(primary) + len(secondary)`
4. 每個站點只出現在一個區域（不重複）
5. 兩個區域內部按 `station_id` 字母順序排列
6. 不存在的站點 ID 回傳 `affected_station=None` + 含 `error` 欄位的結構
7. `total_hops_searched` 回傳輸入的 `hops` 值

**執行測試**：
```bash
pytest tests/integration/ -v -k "delay_ripple"
```
