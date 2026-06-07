# 27 — 修訂報告（Revision Report）

> 開發後期，於整合驗收階段對照**來源資料**（`train-mock-data/`）與**專案說明**
> （`docs/README-teacher-updated.md`）做一次收斂，校準兩處設計：圖綱要命名、票價模型。
> 本報告記錄動機、變更、影響檔案與驗證結果。
>
> 最終設計以根目錄 [`Team09_DESIGN_DOC.md`](../Team09_DESIGN_DOC.md) 為準；`docs/01–26`
> 保留為開發期規劃紀錄，未逐篇改寫。

---

## 修訂一：圖綱要命名收斂

### 動機
專案說明的圖示意與 `Try These Queries` 範例使用 `MetroStation` / `NationalRailStation`
節點與 `METRO_LINK` / `RAIL_LINK` / `INTERCHANGE_TO` 關係。早期實作以單一 `:Station` 搭配
`CONNECTS_TO` / `INTERCHANGE` 表達，雖語意等價，但與說明的命名契約不一致，且不利於以
節點標籤／關係型別做精確查詢與檢核。

### 變更
- **節點**：捷運站標 `:MetroStation`、國鐵站標 `:NationalRailStation`；另對每個節點共掛一個
  `:Station` 標籤，讓跨網最短路徑能以單一標籤書寫。
- **關係**：`METRO_LINK`（捷運同網段）、`RAIL_LINK`（國鐵同網段）、`INTERCHANGE_TO`
  （跨網轉乘，雙向，`travel_time_min=15`）。

### 影響檔案
- `skeleton/seed_neo4j.py`：節點標籤、`_seed_connections` 改帶 `rel_type`、轉乘關係改名。
- `databases/graph/queries.py`：5 段 Cypher 的關係過濾（`'METRO_LINK|RAIL_LINK|INTERCHANGE_TO'`）、
  `INTERCHANGE_TO` 型別判斷、docstring。
- 測試：`tests/unit/test_validate_interchange_feasibility.py`、`tests/unit/test_query_interchange_path.py`、
  `tests/unit/test_gap_fill.py`、`tests/integration/test_query_interchange_path.py`、
  `tests/integration/test_gap_fill.py`。

### 驗證
- 重新 seed 後：`20 :MetroStation`、`10 :NationalRailStation`、`42 METRO_LINK`、`18 RAIL_LINK`、
  `6 INTERCHANGE_TO`（3 對雙向）。
- `query_shortest_route("MS01","MS09")`、`query_interchange_path("MS01","NR02")`、
  `query_station_connections("MS01")` 皆正常（後者回 `METRO_LINK` / `INTERCHANGE_TO`）。

---

## 修訂二：票價模型校準為資料驅動的 base + per-stop

### 動機
來源資料中每個班次／票種都帶 `base_fare_usd` 與 `per_stop_rate_usd`
（國鐵 `national_rail_schedules.json` 的 `fare_classes`；捷運 `metro_schedules.json`），
且專案說明的範例票價（`NR01→NR05` 標準票 `$8.50`）正是
`2.50 + 1.50 × 4 = 8.50`。早期 fare 函式以固定乘數／級距計算，未忠於資料且未用到
`stops_travelled`，故校準為資料驅動公式。

### 變更
- **公式統一**：`total_fare_usd = base_fare_usd + per_stop_rate_usd × stops_travelled`。
- **Schema**：
  - 新增 `national_rail_fare_classes(schedule_id, fare_class, base_fare_usd, per_stop_rate_usd)`，
    PK = `(schedule_id, fare_class)`，外鍵→`national_rail_schedules`（3NF：費率相依於班次＋票種複合鍵）。
  - `metro_schedules` 新增 `per_stop_rate_usd NUMERIC(8,2)`。
- **查詢**：`query_national_rail_fare` 依票種查費率（未知票種退回 `standard`）、
  `query_metro_fare` 改自班次費率計算；兩者回傳新增 `per_stop_rate_usd` 欄位。
- **跨層**：`databases/graph/queries.py` 的 cheapest-route 改讀 `total_fare_usd`。

範例 schema：

```sql
CREATE TABLE national_rail_fare_classes (
    schedule_id       VARCHAR(30)  NOT NULL,
    fare_class        VARCHAR(20)  NOT NULL,
    base_fare_usd     NUMERIC(8,2) NOT NULL,
    per_stop_rate_usd NUMERIC(8,2) NOT NULL,
    PRIMARY KEY (schedule_id, fare_class),
    FOREIGN KEY (schedule_id) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE
);
```

### 影響檔案
- `databases/relational/schema.sql`、`skeleton/seed_postgres.py`
  （新增 `seed_national_rail_fare_classes`、metro per_stop 入庫）、
  `databases/relational/queries.py`、`databases/graph/queries.py`。
- 測試：`tests/unit/test_query_nr_fare.py`、`tests/integration/test_query_metro_fare.py`、
  `tests/unit/test_phase_3.3_performance_boost.py`、`tests/integration/test_e2e_stage1_to_stage3.py`。

### 驗證（live DB 實跑）
| 查詢 | 結果 |
|---|---|
| `query_national_rail_fare("NR_SCH01","standard",4)` | `8.50`（= 2.50 + 1.50×4） |
| `query_national_rail_fare("NR_SCH01","first",4)` | `14.00`（= 4.00 + 2.50×4） |
| `query_metro_fare("MS_SCH01",4)` | `2.00`（= 0.80 + 0.30×4） |

### 已知保留項
`execute_booking` 的訂票金額仍以「班次 base × 票種乘數」作為下單當下的金額快照
（訂票流程未傳入 `stops_travelled`）。此為交易金額快照，與票價查詢（報價）為不同關注點，
不影響票價函式的正確性。

---

## 整體驗證
- 全套測試：`pytest tests/unit tests/integration -q` → **414 passed**。
- 流程：`docker compose down -v && up -d` → `seed_postgres.py` → `seed_neo4j.py` → 測試。
