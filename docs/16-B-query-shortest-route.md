# 16 — 主軸 B｜最短時間路線（APOC Dijkstra）＋單站直連查詢

> **前置條件**：`15-B-neo4j-seed-interchange.md` 完成（完整圖拓撲已建立）
> **後續任務**：`17-B-query-alternative-routes.md`、`18-B-query-interchange-path.md`

---

## 任務目標

在 `databases/graph/queries.py` 中實作：
- `query_shortest_route`：使用 APOC Dijkstra 插件找最短時間路徑，支援跨網路（捷運 ↔ 國鐵）
- `query_station_connections`：列出單一站點的所有直連站（一跳範圍）

**關鍵前提**：`databases/graph/queries.py` 連接 Neo4j 時必須使用預建的連線池：
```python
from databases.graph.connection_pool import get_pool
```
`get_pool()` 是同目錄下 `connection_pool.py` 匯出的工廠函式（**由 Stage 3.3 實作，見 `25-stage3.3-performance-boost.md`**），
回傳已設定好最大 10 個連線的 Neo4j `Driver` 物件。
所有圖形查詢函式都應以 `with get_pool() as driver:` 開頭。

> ⚠️ **開發順序提醒**：`connection_pool.py` 在 `main` 分支上**不存在**，Stage 3.3 完成前若直接執行任何 import `databases.graph.queries` 的測試，Python 會在模組載入時立即拋出 `ModuleNotFoundError`，導致整個測試集失敗。
>
> ⚠️ **scaffold 清理（必做）**：`main` 分支的 `databases/graph/queries.py` scaffold 已有 `from neo4j import GraphDatabase` 和 `def _driver():` 工廠函式。**在開始實作任何查詢函式之前，必須先刪除這兩段代碼**（整個 `_driver` 函式定義，以及頂部的 `GraphDatabase` import 行）。Stage 3.3 的 `performance_boost` 測試會對此檔案做靜態掃描，若這兩者仍存在則測試失敗，且報錯訊息不會指向這裡。
>
> **解決方案：先建立佔位 stub，Stage 3.3 完成後再覆蓋**
>
> 在開始實作 `databases/graph/queries.py` 之前，先在 **`databases/graph/connection_pool.py`** 建立以下最小化 stub：
>
> ```python
> # databases/graph/connection_pool.py — 暫時 stub（Stage 3.3 完成後由正式版覆蓋）
>
> class _StubPool:
>     def __enter__(self):
>         return self
>
>     def __exit__(self, *args):
>         pass
>
>     def session(self, **kwargs):
>         raise RuntimeError("Real Neo4j connection not yet configured (stub pool)")
>
> _pool = None
>
> def get_pool() -> "_StubPool":
>     global _pool
>     if _pool is None:
>         _pool = _StubPool()
>     return _pool
> ```
>
> 這個 stub 讓 `from databases.graph.connection_pool import get_pool` 不再報 `ModuleNotFoundError`，
> 單元測試可以用 `unittest.mock.patch` 替換 `get_pool` 回傳值（見下方範例），
> 整合測試在 Stage 3.3 完成、正式 `connection_pool.py` 覆蓋 stub 後才執行。
>
> **單元測試 mock 範例**（供單元測試參考；測試套件已提供，此處僅說明原理）：
>
> ```python
> from unittest.mock import MagicMock, patch
>
> def test_query_shortest_route_unit():
>     mock_session = MagicMock()
>     mock_record = {
>         "station_ids": ["MS01", "MS03"],
>         "stations": [
>             {"station_id": "MS01", "name": "Central Square", "network_type": "metro"},
>             {"station_id": "MS03", "name": "University",     "network_type": "metro"},
>         ],
>         "total_travel_time_min": 5,
>         "num_legs": 1,
>     }
>     mock_session.run.return_value.single.return_value = mock_record
>
>     mock_pool = MagicMock()
>     mock_pool.__enter__ = lambda s: mock_pool
>     mock_pool.__exit__ = MagicMock(return_value=False)
>     mock_pool.session.return_value.__enter__ = lambda s: mock_session
>     mock_pool.session.return_value.__exit__ = MagicMock(return_value=False)
>
>     with patch("databases.graph.queries.get_pool", return_value=mock_pool):
>         from databases.graph.queries import query_shortest_route
>         result = query_shortest_route("MS01", "MS03")
>
>     assert result["found"] is True
>     assert result["total_travel_time_min"] == 5
> ```

---

## 介面規格

**目標檔案**：`databases/graph/queries.py`

### 函式一：`query_shortest_route`

```python
def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
```

**成功回傳**：

```json
{
  "found": true,
  "origin_id": "MS01",
  "destination_id": "MS09",
  "total_travel_time_min": 24,
  "num_legs": 4,
  "station_ids": ["MS01", "MS03", "MS06", "MS08", "MS09"],
  "stations": [
    {"station_id": "MS01", "name": "Central Square", "network_type": "metro"},
    ...
  ],
  "legs": [
    {
      "from_station_id": "MS01",
      "from_station_name": "Central Square",
      "to_station_id": "MS03",
      "to_station_name": "University",
      "from_network": "metro",
      "to_network": "metro"
    },
    ...
  ]
}
```

**無路徑時回傳**：

```json
{
  "found": false,
  "origin_id": "MS01",
  "destination_id": "INVALID",
  "error": "No path found from MS01 to INVALID",
  "station_ids": [],
  "stations": [],
  "legs": []
}
```

---

### 函式二：`query_station_connections`

```python
def query_station_connections(station_id: str) -> list[dict]:
```

**回傳格式**（list，每個元素：）：

```json
{
  "from_station_id": "MS01",
  "from_station_name": "Central Square",
  "from_network": "metro",
  "to_station_id": "MS02",
  "to_station_name": "City Hall",
  "to_network": "metro",
  "relationship_type": "CONNECTS_TO",
  "travel_time_min": 3,
  "line": "M1"
}
```

站點不存在或無出邊時回傳 `[]`。

---

## 實作邏輯導引

### query_shortest_route 的 Cypher 邏輯

```
Cypher 偽代碼：

MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})

CALL apoc.algo.dijkstra(
    origin,
    destination,
    'CONNECTS_TO|INTERCHANGE',   ← 允許同時跨越兩種關係類型
    'travel_time_min'            ← 用這個屬性作為權重（最小化總時間）
) YIELD path, weight

RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations,
    weight AS total_travel_time_min,
    size(relationships(path)) AS num_legs
```

**`YIELD path, weight` 說明**：
- `path`：最短路徑的 Neo4j Path 物件
- `weight`：最短路徑的總權重（所有關係的 travel_time_min 之和）

**APOC Dijkstra 的前提**：
1. Neo4j 必須載入 APOC 插件（`docker-compose.yml` 已配置）
2. 所有 `CONNECTS_TO` 和 `INTERCHANGE` 關係必須有 `travel_time_min` 整數屬性
3. 若某個關係缺少此屬性，Dijkstra 可能跳過或報錯

### Python 層 query_shortest_route 結構

```
偽代碼：

def query_shortest_route(origin_id, destination_id, network="auto"):
    try:
        with get_pool() as driver:
            with driver.session() as session:
                result = session.run(<<CYPHER>>, origin_id=origin_id, destination_id=destination_id)
                record = result.single()
                
                if record:
                    station_ids = record["station_ids"]
                    stations = record["stations"]
                    total_time = record["total_travel_time_min"]
                    num_legs = record["num_legs"]
                    
                    # 從 station_ids + stations 建構 legs 陣列
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
                    
                    return {
                        "found": True,
                        "origin_id": origin_id,
                        "destination_id": destination_id,
                        "total_travel_time_min": int(total_time) if total_time is not None else 0,
                        "num_legs": num_legs,
                        "station_ids": station_ids,
                        "stations": stations,
                        "legs": legs,
                    }
                
                return {
                    "found": False,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "error": f"No path found from {origin_id} to {destination_id}",
                    "station_ids": [], "stations": [], "legs": [],
                }
    
    except Exception as e:
        return {
            "found": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "error": f"Error querying shortest route: {str(e)}",
            "station_ids": [], "stations": [], "legs": [],
        }
```

**為何整個函式都包在 try/except？**
Neo4j 連線失敗、APOC 未載入、或節點不存在時，都應回傳結構化錯誤，
而非讓例外向上傳播（agent.py 不知道如何處理 Neo4j 例外）。

### query_station_connections 的 Cypher 邏輯

```
Cypher：

MATCH (s:Station {station_id: $station_id})-[r]->(n:Station)
RETURN
    s.station_id   AS from_station_id,
    s.name         AS from_station_name,
    s.network_type AS from_network,
    n.station_id   AS to_station_id,
    n.name         AS to_station_name,
    n.network_type AS to_network,
    type(r)        AS relationship_type,
    r.travel_time_min AS travel_time_min,
    r.line         AS line
ORDER BY n.station_id ASC
```

**注意**：`-[r]->` 的 `r` 是通配符，同時匹配 `CONNECTS_TO` 和 `INTERCHANGE` 出邊。

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：

`query_shortest_route`：
1. 同網路路徑（MS01 → MS09）回傳 `found=True`，`total_travel_time_min > 0`
2. 跨網路路徑（MS01 → NR05）回傳 `found=True`，路徑包含 INTERCHANGE 站點
3. 不存在的站點 ID 回傳 `found=False`（不拋出例外）
4. `station_ids` 的長度 = `num_legs + 1`（邏輯一致性）
5. `legs` 的長度 = `num_legs`

`query_station_connections`：
1. MS01 回傳至少 2 個直連站（多線路交匯站）
2. 不存在的站點 ID 回傳 `[]`
3. 每個元素包含 `relationship_type`（`"CONNECTS_TO"` 或 `"INTERCHANGE"`）

**執行測試**：
```bash
# query_shortest_route — 只有整合測試，無 unit test
pytest tests/integration/test_phase_2.5_gap_fill_integration.py -v -k "shortest_route"

# query_station_connections — unit test 位於 gap_fill_unit
pytest tests/unit/ -v -k "station_connections"
```

> ℹ️ **整合測試說明**：`query_shortest_route` 的整合測試位於
> `tests/integration/test_phase_2.5_gap_fill_integration.py`（`TestQueryShortestRouteIntegration`），
> 使用 `-k "shortest_route"` 可精準定位（pytest `-k` 大小寫不敏感，能匹配類別名稱中的 ShortestRoute）。
>
> ⚠️ **`pytest tests/unit/ -v -k "shortest_route"` 回傳 0 筆**：unit 目錄下沒有 shortest_route 相關
> 測試，此命令不報錯但什麼都沒驗到。請只用上方整合測試命令。
>
> ℹ️ **`query_station_connections` unit test**：位於
> `tests/unit/test_phase_2.5_gap_fill_unit.py::TestQueryStationConnections`，共 2 個測試，
> 使用 `pytest tests/unit/ -v -k "station_connections"` 驗收。
