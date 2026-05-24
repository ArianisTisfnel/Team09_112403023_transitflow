# 17 — 主軸 B｜替代路線查詢（繞過特定站點）

> **前置條件**：`15-B-neo4j-seed-interchange.md` 完成
> **後續任務**：`18-B-query-interchange-path.md`

---

## 任務目標

在 `databases/graph/queries.py` 中實作 `query_alternative_routes`，
使用 `apoc.algo.allSimplePaths` 找出所有不經過特定站點的替代路線（適用於車站關閉/延誤場景）。

---

## 介面規格

**目標檔案**：`databases/graph/queries.py`

```python
def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[dict]:
```

**成功回傳**（list，每個元素：）：

```json
{
  "station_ids": ["NR01", "NR02", "NR04", "NR05"],
  "stations": [
    {"station_id": "NR01", "name": "Central Station", "network_type": "national_rail"},
    ...
  ],
  "legs": [
    {
      "from_station_id": "NR01",
      "from_station_name": "Central Station",
      "to_station_id": "NR02",
      "to_station_name": "Riverside Rail",
      "from_network": "national_rail",
      "to_network": "national_rail"
    },
    ...
  ],
  "avoid_station_id": "NR03"
}
```

**無替代路線時回傳**：`[]`（空串列）
**任何例外時回傳**：`[]`（不拋出例外）

---

## 實作邏輯導引

### 核心 Cypher 邏輯

```
Cypher 偽代碼：

MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})

CALL apoc.algo.allSimplePaths(
    origin,
    destination,
    'CONNECTS_TO|INTERCHANGE',
    5                              ← max_hops 深度限制，防止 OOM
) YIELD path

WHERE length(path) > 0
    AND NOT any(                   ← 過濾：排除所有包含 avoid_station_id 的路徑
        node IN nodes(path)
        WHERE node.station_id = $avoid_station_id
    )

RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations

LIMIT $max_routes
```

**關鍵設計解析**：

1. **`apoc.algo.allSimplePaths`**（而非 `apoc.algo.dijkstra`）：
   Dijkstra 只找一條最優路徑，`allSimplePaths` 列舉所有簡單路徑（不重複節點）。
   這裡的目的是找「替代方案」，所以需要多條路徑。

2. **`NOT any(node IN nodes(path) WHERE node.station_id = $avoid_station_id)`**：
   Neo4j 的清單運算子 `any(x IN list WHERE condition)` 檢查是否有任何元素滿足條件。
   `NOT any(...)` 確保路徑中沒有任何節點的 station_id 等於 avoid_station_id。
   注意：`avoid_station_id` 必須用 Cypher 參數（`$avoid_station_id`），防止 Cypher 注入。

3. **深度限制 `5`**：
   無深度限制的 `allSimplePaths` 在大圖中會因指數爆炸而造成 OOM。
   `5` 是合理上限（轉乘最多 5 次的路線已涵蓋絕大多數實際需求）。

4. **`LIMIT $max_routes`**：
   限制回傳路徑數，預設 3 條。Cypher 的 `$max_routes` 從 Python 參數傳入。

### Python 層結構

```
偽代碼：

def query_alternative_routes(origin_id, destination_id, avoid_station_id, network="auto", max_routes=3):
    try:
        with get_pool() as driver:
            with driver.session() as session:
                result = session.run(
                    <<CYPHER>>,
                    origin_id=origin_id,
                    destination_id=destination_id,
                    avoid_station_id=avoid_station_id,
                    max_routes=max_routes
                )
                
                paths = result.fetch(max_routes)
                
                if not paths:
                    return []
                
                alternative_routes = []
                for path_record in paths:
                    station_ids = path_record["station_ids"]
                    stations = path_record["stations"]
                    
                    legs = []
                    for i in range(len(station_ids) - 1):
                        from_s = stations[i]
                        to_s = stations[i + 1]
                        legs.append({
                            "from_station_id": from_s["station_id"],
                            "from_station_name": from_s["name"],
                            "to_station_id": to_s["station_id"],
                            "to_station_name": to_s["name"],
                            "from_network": from_s["network_type"],
                            "to_network": to_s["network_type"],
                        })
                    
                    alternative_routes.append({
                        "station_ids": station_ids,
                        "stations": stations,
                        "legs": legs,
                        "avoid_station_id": avoid_station_id,
                    })
                
                return alternative_routes
    
    except Exception as e:
        print(f"Error querying alternative routes: {str(e)}")
        return []
```

**`result.fetch(max_routes)` vs `result.data()`**：
- `.fetch(n)` 只取前 n 條記錄，避免不必要的資料傳輸
- `.data()` 取所有結果（在 `allSimplePaths` 上可能返回大量路徑）

---

## 驗收標準

**驗收測試**：

**手動驗收（Neo4j Browser）**：

```cypher
-- 測試情境：NR03 關閉，從 NR01 到 NR05 有替代路線嗎？
MATCH (origin:Station {station_id: 'NR01'})
MATCH (destination:Station {station_id: 'NR05'})
CALL apoc.algo.allSimplePaths(origin, destination, 'CONNECTS_TO|INTERCHANGE', 5) YIELD path
WHERE NOT any(node IN nodes(path) WHERE node.station_id = 'NR03')
RETURN [n IN nodes(path) | n.station_id] AS route
LIMIT 3

// 若 NR01 → NR05 的直接路線必須經過 NR03，則結果應為空
// 若有替代路線（如透過 NR02 繞行），則顯示替代路徑
```

**通過條件**：
1. 當 avoid 站點不在路徑上，回傳的所有路線均不包含該站點
2. 無替代路線時回傳 `[]`（不拋出例外）
3. 任何例外（Neo4j 連線失敗等）回傳 `[]`
4. 每個路線 dict 包含 `avoid_station_id` 欄位（便於呼叫方追蹤）
5. 回傳最多 `max_routes` 條路線（預設 3 條）

**執行相關測試**：
```bash
pytest tests/unit/ -v -k "alternative_routes"
pytest tests/integration/test_phase_2.5_gap_fill_integration.py -v -k "alternative_routes"
```

> ℹ️ **整合測試說明**：`query_alternative_routes` 的整合測試位於
> `tests/integration/test_phase_2.5_gap_fill_integration.py`（`TestQueryAlternativeRoutesIntegration`）。
> 使用 MS01 → MS09 避開 MS03（MS03 在最短路徑上）作為主要測試情境，
> 驗證回傳路線中確實不含 MS03、以及空結果時不拋出例外。
>
> 舊版文件中的 `pytest tests/integration/ -v`（不加 `-k`）會同時觸發所有需要
> 真實 Docker 連線的整合測試，不建議作為單一函式的驗收命令。
