# 13 — 主軸 B｜Neo4j 站點節點種子資料（MS01–MS20 + NR01–NR10）

> **前置條件**：無（B 主軸第一步；Neo4j 服務由 `docker-compose.yml` 提供，已在 `localhost:7688` 運行）
> **後續任務**：`14-B-neo4j-seed-connections.md`

---

## 任務目標

在 `skeleton/seed_neo4j.py` 中實作或確認站點節點的種子邏輯，
將 30 個 `:Station` 節點（20 個捷運站 + 10 個國鐵站）載入 Neo4j 圖形資料庫。
種子資料來源為 `train-mock-data/metro_stations.json` 和 `train-mock-data/national_rail_stations.json`。

---

## 介面規格

**目標檔案**：`skeleton/seed_neo4j.py`

### Neo4j 節點標籤與屬性規格

**標籤**：`:Station`（所有站點統一使用同一標籤）

**必要屬性**：

| 屬性名稱 | 型態 | 說明 |
|---|---|---|
| `station_id` | `String` | 主鍵，如 `"MS01"`、`"NR01"` |
| `name` | `String` | 站點全名，如 `"Central Square"` |
| `network_type` | `String` | `"metro"` 或 `"national_rail"` |
| `lines` | `StringArray` | 路線代碼陣列，如 `["M1", "M2"]`、`["NR1"]` |

**選用屬性**（有助於偵錯，加分項）：

| 屬性名稱 | 型態 | 說明 |
|---|---|---|
| `zone` | `Integer` | 票價區間（捷運用） |
| `is_interchange_metro` | `Boolean` | 是否有換乘捷運 |
| `is_interchange_national_rail` | `Boolean` | 是否有換乘國鐵 |

### 種子後資料庫狀態驗證

在 Neo4j Browser（`localhost:7475`）執行：

```cypher
MATCH (s:Station) RETURN count(s) AS total_stations
// 預期：30

MATCH (s:Station {network_type: 'metro'}) RETURN count(s) AS metro_count
// 預期：20

MATCH (s:Station {network_type: 'national_rail'}) RETURN count(s) AS rail_count
// 預期：10
```

---

## 實作邏輯導引

### seed_neo4j.py 的整體結構

```
偽代碼（seed_neo4j.py 執行流程）：

1. 從 .env 讀取 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD
2. 建立 neo4j.GraphDatabase.driver() 連線
3. 呼叫 seed_metro_stations(driver)
4. 呼叫 seed_national_rail_stations(driver)
5. 呼叫 seed_metro_connections(driver)      ← 第 14 任務
6. 呼叫 seed_rail_connections(driver)       ← 第 14 任務
7. 呼叫 seed_interchange_relations(driver)  ← 第 15 任務
8. 關閉 driver
```

### seed_metro_stations(driver) 邏輯步驟

```
偽代碼：

1. 載入 JSON 檔案：
   with open("train-mock-data/metro_stations.json", encoding="utf-8") as f:
       stations = json.load(f)

2. 開啟 Neo4j session：
   with driver.session() as session:
       for station in stations:
           session.run(
               """
               MERGE (s:Station {station_id: $station_id})
               SET s.name = $name,
                   s.network_type = $network_type,
                   s.lines = $lines
               """,
               station_id=station["metro_station_id"],
               name=station["name"],
               network_type="metro",
               lines=station["lines"]   ← JSON 陣列直接傳入
           )
```

**為什麼用 MERGE 而非 CREATE？**
- `MERGE` 是冪等操作：若節點不存在則建立，若已存在則不重複建立
- `CREATE` 在重複執行時會建立重複節點，造成圖資料污染
- `MERGE` + `SET` 的組合確保屬性永遠是最新值

### seed_national_rail_stations(driver) 邏輯步驟

```
偽代碼：

1. 載入 national_rail_stations.json
2. 與捷運站相同邏輯，但：
   station_id = station["national_rail_station_id"]
   network_type = "national_rail"
   lines = station["lines"]（如 ["NR1", "NR2"]）
```

### JSON 資料結構參考（實作前先確認）

在 `train-mock-data/metro_stations.json` 中，每個站點物件的關鍵欄位：
```
{
  "metro_station_id": "MS01",       ← 對應 station_id 屬性
  "name": "Central Square",
  "lines": ["M1", "M2"],            ← 直接傳入（JSON 陣列 → Cypher List）
  "is_interchange_metro": false,
  "is_interchange_national_rail": true,
  ...
}
```

在 `train-mock-data/national_rail_stations.json` 中：
```
{
  "national_rail_station_id": "NR01",  ← 對應 station_id 屬性
  "name": "Central Station",
  "lines": ["NR1"],
  ...
}
```

### 排錯技巧

執行種子後，若節點數不正確，先清空圖形重新執行：
```cypher
MATCH (n) DETACH DELETE n
```

確認 JSON 檔案讀取路徑正確（相對於執行 `seed_neo4j.py` 的工作目錄）：
```python
import os
print(os.getcwd())  # 應為專案根目錄
```

---

## 驗收標準

**驗收測試**：
節點種子完成後，圖形查詢函式的測試才可正常執行：
```bash
pytest tests/unit/ -v -k "shortest_route or interchange_path"
pytest tests/integration/ -v -k "interchange_path"
```

**手動驗收**：
```bash
python skeleton/seed_neo4j.py
```

執行後在 Neo4j Browser 確認：
```cypher
MATCH (s:Station) 
RETURN s.station_id, s.name, s.network_type, s.lines 
ORDER BY s.network_type, s.station_id
```

**通過條件**：
1. 共 30 個 `:Station` 節點（20 metro + 10 rail）
2. 每個節點有 `station_id`、`name`、`network_type`、`lines` 四個屬性
3. 重複執行 `seed_neo4j.py` 不會產生重複節點（MERGE 幂等性）
4. `station_id` 格式正確：捷運為 `MS01`–`MS20`，國鐵為 `NR01`–`NR10`
