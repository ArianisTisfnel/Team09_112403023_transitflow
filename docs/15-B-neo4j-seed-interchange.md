# 15 — 主軸 B｜Neo4j INTERCHANGE 關係種子（8+ 跨網路換乘點）

> **前置條件**：`14-B-neo4j-seed-connections.md` 完成（捷運和國鐵的站內連接已建立）
> **後續任務**：`16-B-query-shortest-route.md`（所有圖形查詢函式均依賴完整的圖拓撲）

---

## 任務目標

在 `skeleton/seed_neo4j.py` 中建立跨網路的 `[:INTERCHANGE]` 關係，
連結捷運站與國鐵站的換乘點（physical transfer points）。
這些關係是 `query_interchange_path` 和 `validate_interchange_feasibility` 的數據基礎。

---

## 介面規格

**目標檔案**：`skeleton/seed_neo4j.py`

### INTERCHANGE 關係屬性規格

| 屬性名稱 | 型態 | 說明 |
|---|---|---|
| `travel_time_min` | `Integer` | 換乘步行時間（**固定為 15 分鐘**，符合可行性驗證的閾值） |
| `from_network` | `String` | 起點網路（`"metro"` 或 `"national_rail"`） |
| `to_network` | `String` | 終點網路（`"metro"` 或 `"national_rail"`） |

### 已知換乘點清單（從 JSON 資料推導）

根據 `metro_stations.json` 和 `national_rail_stations.json` 中的換乘標記欄位，
以下換乘點是確定存在的（實際以 JSON 資料為準）：

| 捷運站 | 國鐵站 | 換乘類型 |
|---|---|---|
| `MS01` (Central Square) | `NR01` (Central Station) | 主要換乘樞紐 |
| `MS07` (Old Town) | `NR03` (Old Town Halt) | 市區換乘 |
| `MS15` (Ferndale) | `NR07` (Ferndale Junction) | 郊區換乘 |
| 其他有標記的站點 | 對應國鐵站 | — |

**確認方法**：
```python
# 在 seed_neo4j.py 中讀取 JSON 並過濾換乘站
metro_stations = [s for s in metro_data if s.get("is_interchange_national_rail")]
rail_stations = [s for s in rail_data if s.get("is_interchange_metro")]
```

---

## 實作邏輯導引

### 換乘資料讀取策略

```
偽代碼（seed_interchange_relations）：

def seed_interchange_relations(driver):
    # 載入兩個 JSON 檔案
    metro_data = json.load(open("train-mock-data/metro_stations.json"))
    rail_data = json.load(open("train-mock-data/national_rail_stations.json"))
    
    # 建立國鐵站 ID 索引（以便快速查找）
    rail_station_map = {s["national_rail_station_id"]: s for s in rail_data}
    
    with driver.session() as session:
        for ms in metro_data:
            # 只處理有跨網路換乘的捷運站
            if not ms.get("is_interchange_national_rail"):
                continue
            
            nr_id = ms.get("interchange_national_rail_station_id")
            if not nr_id or nr_id not in rail_station_map:
                continue  ← 跳過找不到對應國鐵站的記錄
            
            metro_id = ms["metro_station_id"]
            
            # 建立雙向 INTERCHANGE 關係（捷運→國鐵 和 國鐵→捷運）
            
            # 方向一：捷運 → 國鐵
            session.run("""
                MATCH (m:Station {station_id: $metro_id})
                MATCH (r:Station {station_id: $rail_id})
                MERGE (m)-[i:INTERCHANGE]->(r)
                SET i.travel_time_min = $travel_time,
                    i.from_network = 'metro',
                    i.to_network = 'national_rail'
            """,
            metro_id=metro_id,
            rail_id=nr_id,
            travel_time=15   ← 固定 15 分鐘
            )
            
            # 方向二：國鐵 → 捷運
            session.run("""
                MATCH (r:Station {station_id: $rail_id})
                MATCH (m:Station {station_id: $metro_id})
                MERGE (r)-[i:INTERCHANGE]->(m)
                SET i.travel_time_min = $travel_time,
                    i.from_network = 'national_rail',
                    i.to_network = 'metro'
            """,
            rail_id=nr_id,
            metro_id=metro_id,
            travel_time=15
            )
```

### 為何 travel_time_min 固定為 15？

`validate_interchange_feasibility` 函式的邏輯：
```
for leg in path.legs:
    if leg.relationship_type == "INTERCHANGE":
        if leg.travel_time_min < 15:
            return False  ← 不可行
return True  ← 所有換乘都 >= 15 分鐘
```

若設為 15，`validate_interchange_feasibility` 對標準路線回傳 `True`（可行）。
若設為 14，所有有換乘的路線都會被判定為不可行——這會導致測試失敗。

**此處的設計決策影響後續測試**，請確認 15 分鐘是正確設定。

### INTERCHANGE vs CONNECTS_TO 的語意差異

| 特性 | `CONNECTS_TO` | `INTERCHANGE` |
|---|---|---|
| 代表 | 同一網路內的站間行駛 | 不同網路間的步行換乘 |
| 節點關係 | 同 network_type | 不同 network_type |
| travel_time_min | 3–15 分鐘（行駛） | 15 分鐘（步行） |
| 用於 Dijkstra | 是（主要邊） | 是（換乘邊） |

---

## 驗收標準

**驗收測試**：
INTERCHANGE 關係種子完成後，換乘路徑與可行性驗證測試才可正常執行：
```bash
pytest tests/unit/ -v -k "interchange_path or interchange_feasibility"
pytest tests/integration/ -v -k "interchange_path"
```

**手動驗收（Neo4j Browser）**：

```cypher
-- 確認 INTERCHANGE 關係存在
MATCH ()-[r:INTERCHANGE]->() RETURN count(r)
// 預期：至少 8 條（4個換乘點 × 雙向 = 8 條，可能更多）

-- 確認換乘關係連接捷運和國鐵
MATCH (m:Station {network_type: 'metro'})-[r:INTERCHANGE]->(n:Station {network_type: 'national_rail'})
RETURN m.station_id, m.name, n.station_id, n.name, r.travel_time_min

-- 確認 travel_time_min = 15（用於可行性驗證）
MATCH ()-[r:INTERCHANGE]->() WHERE r.travel_time_min <> 15 RETURN count(r)
// 預期：0

-- 端對端路徑測試：從捷運站到國鐵站
MATCH (start:Station {station_id: 'MS01'})
MATCH (end:Station {station_id: 'NR05'})
CALL apoc.algo.dijkstra(start, end, 'CONNECTS_TO|INTERCHANGE', 'travel_time_min')
YIELD path, weight
RETURN [n IN nodes(path) | n.station_id] AS route, weight
// 預期：有結果，且路徑包含 INTERCHANGE 換乘點
```

**通過條件**：
1. 至少 8 條 INTERCHANGE 關係（雙向）
2. 每條 INTERCHANGE 關係的 `travel_time_min = 15`
3. `pytest tests/unit/ -v -k "interchange_feasibility"` 全數通過
4. 跨網路 Dijkstra 查詢（MS01 → NR05）有回傳結果
