# Stage 1 — 主軸 B 實作報告:Neo4j 圖形查詢層

> **作者**:廖俊傑(主軸 B)
> **涵蓋範圍**:`docs/13`–`docs/20`(主軸 B 全部任務)
> **狀態**:程式碼 8/8 函式完成,本地驗收全部通過
> **最後更新**:2026-05-27

---

## 一、實作範圍

### 1.1 修改的檔案

| 檔案 | 內容 | 對應 docs |
|---|---|---|
| `databases/graph/queries.py` | scaffold 清理 + 7 個 Neo4j 查詢函式 + 1 個純 Python 驗證器 | docs/16–20 |
| `databases/graph/connection_pool.py` | 新建最小化 stub(`get_pool()`) | docs/16 Rule 8 |
| `skeleton/seed_neo4j.py` | 5 個種子函式(節點 × 2 + 關係 × 3) | docs/13–15 |

### 1.2 完成的函式清單

#### 種子資料(`skeleton/seed_neo4j.py`)

| 函式 | 行為 | 對應 docs |
|---|---|---|
| `seed_metro_stations(session, stations)` | 載入 20 個 `:Station` 節點(`network_type='metro'`) | docs/13 |
| `seed_national_rail_stations(session, stations)` | 載入 10 個 `:Station` 節點(`network_type='national_rail'`) | docs/13 |
| `_seed_connections(session, stations, default_time_min)` | 共用 helper:從 `adjacent_stations` 建 `CONNECTS_TO` 邊 | docs/14 |
| `seed_metro_connections(session, stations)` | 42 條捷運 `CONNECTS_TO` 邊(預設 3 分鐘兜底) | docs/14 |
| `seed_national_rail_connections(session, stations)` | 18 條國鐵 `CONNECTS_TO` 邊(預設 15 分鐘兜底) | docs/14 |
| `seed_interchange_relations(session, metro, rail)` | 6 條跨網路 `INTERCHANGE` 邊(`travel_time_min=15`,雙向) | docs/15 |

#### 圖形查詢(`databases/graph/queries.py`)

| 函式 | 用途 | 對應 docs |
|---|---|---|
| `query_shortest_route(origin, dest, network)` | 最短時間路徑(APOC Dijkstra) | docs/16 |
| `query_station_connections(station_id)` | 列出某站所有出邊(`CONNECTS_TO` + `INTERCHANGE`) | docs/16 |
| `query_alternative_routes(origin, dest, avoid, network, max_routes)` | 避開某站的替代路線(`allSimplePaths` + 節點過濾) | docs/17 |
| `query_interchange_path(origin, dest)` | 必含 INTERCHANGE 的路徑(兩段式 Cypher) | docs/18 |
| `validate_interchange_feasibility(path_details)` | 純 Python 驗證 15 分鐘最低轉乘時間 | docs/18 |
| `query_delay_ripple(affected_station_id, hops)` | 影響圈分類(三段式 BFS) | docs/19 |
| `query_cheapest_route(origin, dest, network, fare_class)` | 最低票價路徑(跨主軸呼叫 Track A 票價函式) | docs/20 |

### 1.3 最終 Neo4j 圖規模

```
節點:30 個 :Station
  ├── 20 metro    (MS01–MS20)
  └── 10 rail     (NR01–NR10)

關係:66 條邊
  ├── 60 CONNECTS_TO    (42 metro + 18 rail,雙向)
  └──  6 INTERCHANGE    (3 對換乘樞紐 × 雙向)

跨網路驗證:MS01 → NR05 = 52 分鐘
  路徑:MS01 ─→ MS07 ──[INTERCHANGE]──→ NR03 ─→ NR04 ─→ NR05
```

---

## 二、設計決策

### 2.1 為什麼用 `MERGE` 不用 `CREATE`?

種子腳本所有節點和邊都用 `MERGE` 寫入,而非 `CREATE`。

| 寫法 | 重跑第二次發生? |
|---|---|
| `CREATE (s:Station {...})` | 建出第二個重複節點 |
| `MERGE (s:Station {station_id: $id})` + `SET` 其他屬性 | 找到已存在的節點,只更新屬性 |

這個選擇符合 `docs/00-README.md` 第 5 條規則(「Neo4j 種子資料使用 MERGE」),確保 `seed_neo4j.py` 重跑時不會建出重複圖,且屬性能持續更新。

實際驗證:連跑兩次 `python skeleton/seed_neo4j.py`,結果都是 30 節點 + 66 條邊,**沒有產生重複**。

---

### 2.2 雙向圖實作策略(`CONNECTS_TO`)

`docs/14` 第 113-119 行給了三個選項:
- 策略 1:`(a)→(b)` 和 `(b)→(a)` 各建一條
- 策略 2:只建單向 + 查詢時用 `-[]-`(無方向)
- 策略 3:APOC Dijkstra 遵循方向

採用**策略 1**,理由:
- `query_shortest_route` 使用 `apoc.algo.dijkstra`,**遵循關係方向**
- 單向圖會導致反向路徑找不到(例如能從 MS01 到 MS02,卻不能從 MS02 到 MS01)

**實作技巧**:不用顯式寫反向 Cypher。因為 JSON 資料兩端各自列了鄰接(MS01.adjacent 列 MS02,MS02.adjacent 也列 MS01),所以**遍歷一次** `(每個站, 每個鄰居)` 就自然產生雙向圖。

---

### 2.3 `INTERCHANGE.travel_time_min = 15`(規格常數)

`docs/15` 明確要求所有 `INTERCHANGE` 邊的 `travel_time_min` **必須是 15**,理由如 `docs/18` 所述:

```
validate_interchange_feasibility 邏輯:
  for leg in path.legs:
    if leg.relationship_type == "INTERCHANGE":
      if leg.travel_time_min < 15:
        return False   # 不可行
  return True
```

若種子寫 14,所有含轉乘的路徑會被判定不可行 → 測試失敗。

**實作上**:把 `15` 寫進 Cypher `SET i.travel_time_min = 15`(不用參數),確保不會被外部覆蓋。同時 `validate_interchange_feasibility` 內也定義模組層級常數 `_MIN_INTERCHANGE_MIN = 15`,做為單一真理來源。

---

### 2.4 「`get_pool()`」模式(取代舊版 `_driver()`)

`docs/00-README.md` 規則 8 要求:

> `databases/graph/queries.py` 開始實作前必須移除頂部的 `from neo4j import GraphDatabase` 與 `def _driver():`,改用 `from databases.graph.connection_pool import get_pool`

實作時建立了 stub 版的 `connection_pool.py`(過渡用),內容為 `_StubPool` 類別,其 `session()` 主動拋 `RuntimeError`。

**設計意圖**(stub 主動報錯而非沉默 mock):若有人誤將整合測試跑在 stub 上,會立刻失敗,避免靜默通過。docs/25 的正式 `Neo4jConnectionPool`(LRU + max 10 connections)會在後續階段覆蓋此 stub,**屆時所有 query 函式不需修改任何一行**即可對接真實連線。

---

### 2.5 例外處理策略(structured fallback, never raise)

所有 query 函式都遵循 `AI_SESSION_CONTEXT.md` 規則:**找不到結果回結構化錯誤,不向上 raise**。

實作模式:
```python
def query_xxx(...):
    try:
        with get_pool() as driver:
            with driver.session() as session:
                ...
    except Exception as e:
        return _empty_result(..., error=f"... {str(e)}")
```

外層 `try/except` 統一捕捉:Neo4j 連線錯誤、Cypher 語法錯誤、APOC 未載入、stub 主動拋出的 `RuntimeError`,全部轉成 `found=False` + `error` 欄位的結構化結果。

優點:`skeleton/agent.py` 不需要處理 `try/except`,只要看 `found` 或 list 是否空即可。

---

### 2.6 `query_delay_ripple` 三段式查詢(避開 Cypher 語法限制)

Neo4j **不允許**在可變長度路徑模式裡使用 Cypher 參數:

```cypher
MATCH (center)-[*1..$hops]-(neighbor)  -- ❌ 不允許
MATCH (center)-[*1..2]-(neighbor)      -- ✅ 字面量可
```

**解法**:在 Python 層 `int()` 強制轉型 + 夾範圍 `[1, 5]`,再用 `.format()` 嵌入 Cypher 字串。

```python
hops = max(1, min(int(hops), 5))   # 防注入 + 防 BFS 暴衝
ripple_query = "MATCH (center)-[*1..{hops}]-(neighbor) ...".format(hops=hops)
```

`int()` 確保 `hops` 是數字(無法注入 Cypher),夾範圍防止 `hops=1000` 導致 BFS 失控。

三段式設計(`docs/19`):
1. **中心站確認** — 找不到 fail fast
2. **可變長度遍歷** — 用 `DISTINCT` 去重 N 跳內的所有鄰居
3. **每個鄰居跑 shortestPath** — 取精確跳數做 primary / secondary 分類

---

### 2.7 `query_cheapest_route` 跨主軸依賴與兜底機制

`docs/20` 要求 `query_cheapest_route` 對每個路徑段呼叫 Track A 函式計算票價:

```python
from databases.relational.queries import (
    query_metro_fare, query_metro_schedules,
    query_national_rail_availability, query_national_rail_fare,
)
```

**Track A 目前還在 stub 階段**(`raise NotImplementedError`)。實作採用 `docs/20` 第 174-178 行規範的兜底機制:

```python
def _segment_fare_usd(from_id, to_id, fare_class):
    try:
        if from_id.startswith("MS") and to_id.startswith("MS"):
            scheds = query_metro_schedules(...)
            if scheds: return query_metro_fare(...)
            return 1.50   # 捷運找不到班次的兜底
        ...
    except Exception:
        return 5.00       # Track A stub raise 走這條
```

**兩層兜底分工**:
- **「找不到資料」兜底**(Track A 回 `[]` 或 `None`):用 `1.50`(metro)/ `5.00`(rail)
- **「例外」兜底**(Track A raise NotImplementedError、連線失敗等):統一 `5.00`(遵循 docs/20 第 178 行)

**現況**:Track A 全部 stub → 所有 segment 都觸發例外兜底 → 結果全部 `5.00`。**等 Track A PR #1 merge 後,自動切換到真實票價計算,程式不需修改**。

---

## 三、關鍵 SQL / Cypher

### 3.1 跨網路 Dijkstra(`query_shortest_route`)

```cypher
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.dijkstra(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',     ← 同時允許兩種邊
    'travel_time_min'              ← 用此屬性作為權重
) YIELD path, weight
RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {station_id: n.station_id, name: n.name, network_type: n.network_type}] AS stations,
    weight AS total_travel_time_min,
    size(relationships(path)) AS num_legs
```

**為何用 `CONNECTS_TO|INTERCHANGE`**(用 `|` 分隔)?讓 Dijkstra 同時走兩種邊,自動跨越網路邊界。實測 `MS01 → NR05` 會自然走 `MS01 →(M2)→ MS07 →(INTERCHANGE)→ NR03 →(NR1)→ NR04 →(NR1)→ NR05`,52 分鐘。

---

### 3.2 必經 INTERCHANGE 過濾(`query_interchange_path`)

```cypher
CALL apoc.algo.allSimplePaths(origin, dest, 'CONNECTS_TO|INTERCHANGE', 10) YIELD path
WHERE length(path) > 0
  AND any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')   ← 關鍵過濾
RETURN ...
```

`any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')` 確保**至少有一個關係是 INTERCHANGE 類型**,排除純捷運或純國鐵路徑。

---

### 3.3 避站節點過濾(`query_alternative_routes`)

```cypher
CALL apoc.algo.allSimplePaths(origin, dest, 'CONNECTS_TO|INTERCHANGE', 5) YIELD path
WHERE length(path) > 0
  AND NOT any(node IN nodes(path) WHERE node.station_id = $avoid_station_id)
RETURN ...
LIMIT $max_routes
```

關鍵點:`avoid_station_id` 使用 Cypher 參數 `$avoid_station_id`(防注入)。深度限制 5 防止指數爆炸。

---

### 3.4 影響圈三段式 BFS(`query_delay_ripple`)

```cypher
# 第一段:確認中心站
MATCH (center:Station {station_id: $station_id})
RETURN center.station_id, center.name, center.network_type

# 第二段:所有 N 跳內鄰居(可變長度路徑;{hops} 用 Python f-string 嵌入)
MATCH (center:Station {station_id: $station_id})
MATCH (center)-[*1..{hops}]-(neighbor:Station)
WHERE neighbor.station_id <> center.station_id
RETURN DISTINCT neighbor.station_id, neighbor.name, neighbor.network_type, neighbor.lines

# 第三段:每個鄰居的精確跳數
MATCH (center:Station {station_id: $center_id})
MATCH (neighbor:Station {station_id: $neighbor_id})
MATCH path = shortestPath((center)-[*1..{hops}]-(neighbor))
RETURN length(path) AS hop_count
```

---

## 四、本地驗收結果

### 4.1 種子驗證(在實際 Neo4j 跑)

| 指標 | 結果 | 預期 |
|---|---|---|
| `MATCH (s:Station) RETURN count(s)` | 30 | 30 |
| Metro 節點(`network_type='metro'`) | 20 | 20 |
| Rail 節點(`network_type='national_rail'`) | 10 | 10 |
| `CONNECTS_TO` 邊總數 | 60 | ≥ 50 |
| `INTERCHANGE` 邊總數 | 6 | ≥ 6(3 對 × 雙向) |
| 所有 `INTERCHANGE.travel_time_min` 是否 = 15 | 是 | 必須 |
| 屬性完整性(無 NULL) | 0 個有缺 | 0 |
| 孤立節點 | 0 個 | 0 |
| 冪等性(重跑 2 次後計數) | 30/60/6 不變 | 不變 |

### 4.2 查詢函式驗證

| 函式 | 測試案例 | 結果 |
|---|---|---|
| `query_shortest_route` | MS01 → MS09 | 4 leg, 11 分鐘 |
| `query_shortest_route` | MS01 → NR05(跨網路) | 4 leg, 52 分鐘,含 INTERCHANGE at MS07 |
| `query_shortest_route` | MS01 → INVALID | `found=False` |
| `query_station_connections` | MS01 | 5 條邊(4 CONNECTS_TO + 1 INTERCHANGE) |
| `query_station_connections` | INVALID | `[]` |
| `query_alternative_routes` | MS01 → MS09 avoid MS03 | 3 條路徑,皆不含 MS03 |
| `query_alternative_routes` | MS20 → MS01 avoid MS05 | `[]`(MS05 是 MS20 唯一出邊) |
| `query_interchange_path` | MS01 → NR05 | 5 站路徑,含 1 個 15-min INTERCHANGE |
| `validate_interchange_feasibility` | 9 個邊界案例(含跨午夜) | 全部正確 |
| `query_delay_ripple` | NR03, hops=2 | primary `[MS07, NR02, NR04]` + secondary `[MS01, MS18, NR01, NR05]` |
| `query_delay_ripple` | INVALID | `affected_station=None` + error |
| `query_cheapest_route` | NR01 → NR05 via stub | 10 paths enumerated; 全段走兜底 |

### 4.3 邊界與錯誤處理

- **stub 主動 raise**:所有函式透過 `with get_pool()` 都會被外層 `try/except` 接住,回 `found=False` 或 `[]`
- **`hops` 邊界**:`query_delay_ripple` 對 `hops=0/10/'abc'` 都正確處理(夾範圍 + 型別預設)
- **跨午夜時間計算**:`validate_interchange_feasibility` 對 `23:50 → 00:10`(20 分鐘)正確判定為可行

---

## 五、已知限制

### 5.1 `allSimplePaths` 在雙向圖會回重複路徑

當 `(a)→(b)` 和 `(b)→(a)` 兩條邊都存在時(這專案所有 CONNECTS_TO 都是),`allSimplePaths` 可能回傳「`station_ids` 相同但走不同關係實例」的多條路徑。

**現況**:不去重(Cypher 原生輸出)。
**理由**:`docs/17`、`docs/20` 規格均未要求去重,且這些「重複」對應的是真實不同的邊序列,只是節點序列剛好相同。
**影響**:`query_alternative_routes` 和 `query_cheapest_route` 回傳的 `cheapest_routes[0]` 和 `cheapest_routes[1]` 可能視覺上看起來一樣。

如果未來需要去重,可在 Python 層用 `tuple(station_ids)` 當 dedup key。

---

### 5.2 `query_cheapest_route` 整合驗證待 Track A 上線

目前 Track A(`databases/relational/queries.py`)所有 `query_*_fare` / `query_*_availability` 都是 stub(`raise NotImplementedError`)。

**現況**:所有路徑段都觸發例外兜底,實際票價計算邏輯未跑過真實數據。
**等待**:Track A PR #1 merge 進 main 後,自然會切換到真實票價計算。
**驗證計畫**:Track A merge 後,跑 `query_cheapest_route("NR01", "NR05")` 應該看到:
- 路徑段票價是真實數字(不再是兜底 5.00)
- `cheapest_routes` 按 `total_fare_usd` 升序排列
- `routes_found_total >= num_cheapest`

---

### 5.3 `network` 參數目前未使用

`query_shortest_route` 和 `query_cheapest_route` 的 `network: str = "auto"` 參數**目前不影響行為**。

**現況**:無論 `network` 是 `'metro'`、`'rail'` 還是 `'auto'`,Cypher 都用相同的 `'CONNECTS_TO|INTERCHANGE'`,讓 Dijkstra / allSimplePaths 自然在整個圖找最佳路徑。
**理由**:`docs/16`、`docs/20` 規格未明確定義 `network` 的過濾語意。Dijkstra 對跨網路路徑的處理已經正確(自動經 INTERCHANGE)。
**未來可能擴充**:若需要強制 metro-only 或 rail-only,可在 Cypher 加 `WHERE all(n IN nodes(path) WHERE n.network_type = $network)`。

---

### 5.4 文件規格與實際資料 / 較新版本的偏差

實作過程發現三處 docs 與實際狀況不一致,實作以**較新規格 / 實際資料**為準:

| 位置 | docs 寫法 | 實際正確寫法 | 採用 |
|---|---|---|---|
| `docs/13` 第 95 行 | `station["metro_station_id"]` | `station["station_id"]`(JSON 實際欄位) | JSON 為準 |
| `docs/15` 標題 + 168 行 | 「8+ INTERCHANGE 關係」(預期 4 對) | JSON 只有 3 對 × 2 = 6 條 | JSON 為準 |
| `docs/19` 簽名 | `affected_station_id, hops` → `dict` | AI_SESSION_CONTEXT.md 寫 `delayed_station_id, hops` → `list[dict]` | docs/19 為準(較新) |
| `docs/17` 簽名 | `list[dict]`(每 dict 一條路線) | stub 寫 `list[list[dict]]`(舊版) | docs/17 為準(較新) |

每個偏差都在對應 commit body 中標註,可供 review 時對照。

---

## 六、測試結果摘要

### 6.1 已執行的本地驗收

所有 docs/13–docs/20 規格中標明的 acceptance test 全部通過(對著實際 Neo4j 跑 Cypher + Python 端結構驗證)。詳細測試案例見 §4。

### 6.2 待 Track A 完成後的整合驗證

| 驗證項 | 觸發條件 | 預期 |
|---|---|---|
| `query_cheapest_route` 真實票價排序 | Track A PR #1 merge | 段落票價是真實值,`cheapest_routes` 按 `total_fare_usd` 升序 |
| Agent 端 tool routing | `skeleton/agent.py` 升級到 docs/24 SOLID 重構 | LLM 能透過自然語言觸發 7 個 graph query |
| Neo4j 連線池效能 | `docs/25` 正式版 `connection_pool.py` 覆蓋 stub | 多執行緒查詢能共享最多 10 個連線 |

### 6.3 完整 pytest 套件

康睿恩主軸負責的 `tests/unit/`、`tests/integration/` 套件目前是空殼。
**等他撰寫測試後**,主軸 B 函式應該全部通過:

```bash
pytest tests/unit/ -v -k "station_connections or alternative_routes or interchange_path or interchange_feasibility"
pytest tests/integration/ -v -k "shortest_route or delay_ripple or cheapest_route"
```

---

## 七、後續工作 / 待協同

### 7.1 跨主軸協同

| 工作 | 依賴 | 影響 |
|---|---|---|
| Track A PR #1 merge | 陳玟茹 | 解鎖 `query_cheapest_route` 真實票價驗證 |
| Stage 3.3 connection_pool 正式版(docs/25) | 康睿恩 | 覆蓋目前 stub,自動啟用真實 Neo4j 連線 |
| Stage 3.2 agent DI 重構(docs/24) | 康睿恩 | 主軸 B 函式被 agent 動態載入 |

### 7.2 主軸 B 自身的選做加分項

不在 docs/13–20 範圍內,但有時間可以做:
- 路徑視覺化(`query_shortest_route` 結果輸出 graphviz / mermaid)
- 路徑去重機制(`allSimplePaths` 雙向圖重複問題)
- `network='metro'/'rail'` 過濾語意實作

---

## 八、外部依賴與相關文件

- **規格依據**:
  - [docs/13-B-neo4j-seed-stations.md](../../docs/13-B-neo4j-seed-stations.md)
  - [docs/14-B-neo4j-seed-connections.md](../../docs/14-B-neo4j-seed-connections.md)
  - [docs/15-B-neo4j-seed-interchange.md](../../docs/15-B-neo4j-seed-interchange.md)
  - [docs/16-B-query-shortest-route.md](../../docs/16-B-query-shortest-route.md)
  - [docs/17-B-query-alternative-routes.md](../../docs/17-B-query-alternative-routes.md)
  - [docs/18-B-query-interchange-path.md](../../docs/18-B-query-interchange-path.md)
  - [docs/19-B-query-delay-ripple.md](../../docs/19-B-query-delay-ripple.md)
  - [docs/20-B-query-cheapest-route.md](../../docs/20-B-query-cheapest-route.md)

- **協同文件**:
  - [TEAM.md](../../TEAM.md) — 分工與 Git workflow
  - [AI_SESSION_CONTEXT.md](../../AI_SESSION_CONTEXT.md) — Cross-track 函式簽名契約

- **本主軸 GitHub PR**:
  - PR #3 — scaffold cleanup(`feature/liao/scaffold-cleanup`)
  - PR #2 — Neo4j seed(`feature/liao/neo4j-seed`)
  - (待開) Graph queries(`feature/liao/query-shortest-route`)
