# 14 — 主軸 B｜Neo4j CONNECTS_TO 關係種子（捷運 M1–M4 + 國鐵 NR1–NR2）

> **前置條件**：`13-B-neo4j-seed-stations.md` 完成（所有 `:Station` 節點已存在）
> **後續任務**：`15-B-neo4j-seed-interchange.md`

---

## 任務目標

在 `skeleton/seed_neo4j.py` 中實作站點間的 `[:CONNECTS_TO]` 關係種子邏輯，
建立捷運四條線路（M1–M4）以及國鐵兩條線路（NR1–NR2）的所有雙向連接關係。

---

## 介面規格

**目標檔案**：`skeleton/seed_neo4j.py`

### CONNECTS_TO 關係屬性規格

| 屬性名稱 | 型態 | 說明 |
|---|---|---|
| `travel_time_min` | `Integer` | 兩站間行駛時間（分鐘），**這是 Dijkstra 的權重欄位** |
| `line` | `String` | 路線代碼，如 `"M1"`、`"NR1"` |
| `distance_km` | `Float` | 站間距離（選用） |

### 種子後資料庫狀態驗證

```cypher
MATCH ()-[r:CONNECTS_TO]->() RETURN count(r) AS total_connects
// 預期：至少 50 條（捷運 ~40 + 國鐵 ~12）

MATCH ()-[r:CONNECTS_TO {line: 'M1'}]->() RETURN count(r)
// M1 線路的所有連接關係

MATCH (a:Station {station_id: 'MS01'})-[r:CONNECTS_TO]->(b:Station)
RETURN b.station_id, r.travel_time_min, r.line
// 確認 MS01 的直連站點
```

---

## 實作邏輯導引

### 路線拓撲設計原則

在建立 `CONNECTS_TO` 關係前，需先從 JSON 資料推導出路線拓撲：

**捷運路線的鄰接關係資料來源**：`train-mock-data/metro_stations.json`
每個站點物件包含一個 `adjacent_stations` 欄位（或類似命名），列出直連站點。
若 JSON 不包含明確的鄰接清單，則從 `metro_schedules.json` 的路線推導。

**國鐵路線的鄰接關係資料來源**：`train-mock-data/national_rail_stations.json`
同樣從 `adjacent_stations` 欄位或 `national_rail_schedules.json` 推導。

### CONNECTS_TO 關係建立邏輯

```
偽代碼（建立捷運連接）：

def seed_metro_connections(driver):
    # 方法一：從 metro_stations.json 的 adjacent_stations 欄位讀取
    with open("train-mock-data/metro_stations.json") as f:
        stations = json.load(f)
    
    adjacency_map = {}
    for station in stations:
        station_id = station["metro_station_id"]
        adjacency_map[station_id] = station.get("adjacent_stations", [])
    
    with driver.session() as session:
        for station_id, neighbors in adjacency_map.items():
            for neighbor_info in neighbors:
                # neighbor_info 可能是 dict {station_id, line, travel_time_min}
                # 或純字串（需要查詢 lines 判斷所屬路線）
                
                neighbor_id = neighbor_info.get("station_id") or neighbor_info
                line = neighbor_info.get("line", "M1")
                travel_time_min = neighbor_info.get("travel_time_min", 3)
                
                session.run("""
                    MATCH (a:Station {station_id: $from_id})
                    MATCH (b:Station {station_id: $to_id})
                    MERGE (a)-[r:CONNECTS_TO {line: $line}]->(b)
                    SET r.travel_time_min = $travel_time_min
                """,
                from_id=station_id,
                to_id=neighbor_id,
                line=line,
                travel_time_min=travel_time_min
                )
```

### MERGE 關係的唯一性策略

Neo4j 的 `MERGE` 在關係上的語意是：若**完全相同**（相同端點 + 相同類型 + 相同屬性）的關係存在則跳過，否則建立。

但如果 `travel_time_min` 作為 MERGE 的鍵，重複執行可能建立重複關係（因為 SET 改變了屬性值）。
**推薦寫法**：只用關係類型和路線代碼做 MERGE 鍵，然後 SET 其餘屬性：

```
MERGE (a)-[r:CONNECTS_TO {line: $line}]->(b)
SET r.travel_time_min = $travel_time_min
```

這確保每條 `(a)-[:CONNECTS_TO {line: 'M1'}]->(b)` 關係只存在一條。

### 雙向連接的處理方式

捷運和國鐵的路線**在實際應用中是雙向的**（可以從 A 到 B，也可以從 B 到 A）。
但 Neo4j 的關係有方向性。

**三種策略**（選一即可）：
1. **建立雙向關係**：`(a)→(b)` 和 `(b)→(a)` 各建立一條（總關係數是鄰接邊數 × 2）
2. **建立單向但用無方向查詢**：只建立 `(a)→(b)`，Cypher 查詢時使用 `-[]-` 而非 `-[]->`（無方向查詢）
3. **APOC Dijkstra 的方向性**：`apoc.algo.dijkstra` 遵循關係方向，若選策略 2 則需確認 Cypher 支援雙向遍歷

**本專案採用策略 1（雙向建立）**，因為 `query_shortest_route` 使用 `apoc.algo.dijkstra`，它遵循關係方向。
只建立單向關係會導致 Dijkstra 找不到反向路徑。

### 行駛時間（travel_time_min）設定原則

若 JSON 中無明確的 `travel_time_min` 欄位，使用以下預設值：
- 捷運相鄰站：**3 分鐘**（市區短距離）
- 國鐵相鄰站：**15 分鐘**（城際中距離）
- INTERCHANGE 換乘步行：**15 分鐘**（跨網路步行連接）

這些預設值確保 `validate_interchange_feasibility` 中 15 分鐘閾值的測試可以通過。

---

## 驗收標準

**驗收測試**：
CONNECTS_TO 關係種子完成後，路徑查詢與延誤漣漪測試才可正常執行：
```bash
pytest tests/unit/ -v -k "shortest_route or interchange_path"
pytest tests/integration/ -v -k "delay_ripple"
```

**手動驗收（在 Neo4j Browser 執行）**：

```cypher
-- 確認關係總數
MATCH ()-[r:CONNECTS_TO]->() RETURN count(r)
// 至少 50 條

-- 確認從 MS01 可以到達 MS20（連通性測試）
MATCH path = shortestPath((a:Station {station_id: 'MS01'})-[*]-(b:Station {station_id: 'MS20'}))
RETURN length(path)
// 應有結果（表示圖連通）

-- 確認所有站點都有至少一條連接（孤立節點檢查）
MATCH (s:Station) WHERE NOT (s)-[:CONNECTS_TO]-() RETURN s.station_id
// 預期：無孤立站點（或僅有特殊設計的終端站有單向）

-- 確認 travel_time_min 屬性存在
MATCH ()-[r:CONNECTS_TO]->() WHERE r.travel_time_min IS NULL RETURN count(r)
// 預期：0
```

**通過條件**：
1. 捷運 M1–M4 的所有相鄰站點間有 `CONNECTS_TO` 關係（雙向）
2. 國鐵 NR1–NR2 的所有相鄰站點間有 `CONNECTS_TO` 關係（雙向）
3. 每條關係有 `travel_time_min` 和 `line` 屬性
4. `pytest tests/unit/ -v -k "interchange_path"` 通過（透過 mock）
