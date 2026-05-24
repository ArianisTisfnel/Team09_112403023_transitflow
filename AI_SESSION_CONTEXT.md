# AI Session Context — TransitFlow

**How to use this file:**
At the start of every AI coding session, paste the full contents of this file as your first message to your AI assistant. This gives the AI the context it needs to produce code that fits your codebase and is consistent with your teammates' work.

**Who maintains this file:**
Whoever makes a schema change or architectural decision updates this file in the same commit. Treat it like a team contract.

---

## Project Overview

TransitFlow is a Python-based AI chat assistant for a fictional transit operator. It queries three databases — PostgreSQL (relational + vector), Neo4j (graph) — and uses an LLM to answer user questions. Our task as students is to design the database schema and implement the query functions in `databases/relational/queries.py` and `databases/graph/queries.py`.

## Tech Stack

- Language: Python 3.11+
- Relational DB: PostgreSQL via `psycopg2` with `RealDictCursor`
- Graph DB: Neo4j via the `neo4j` Python driver
- Vector search: `pgvector` extension (already implemented — do not modify)
- Web UI: Gradio
- LLM: Google Gemini or local Ollama (configured via `.env`)

## Coding Conventions

- **Naming:** `snake_case` for all Python names and SQL identifiers
- **Docstrings:** All functions must have a docstring with `Args:` and `Returns:` sections
- **Return types:** Use type hints. Read-only functions return `list[dict]` or `Optional[dict]`
- **Empty results:** Return `[]` or `None` (as documented), never raise an exception for "not found"
- **SQL:** Use `%s` placeholders for all user inputs — never string-format into SQL
- **Relational pattern:** Use `_connect()` helper + `psycopg2.extras.RealDictCursor`:
  ```python
  with _connect() as conn:
      with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
          cur.execute("SELECT ...", (param,))
          return [dict(row) for row in cur.fetchall()]
  ```
- **Graph pattern:** Use `_driver()` helper + session:
  ```python
  with _driver() as driver:
      with driver.session() as session:
          result = session.run("MATCH ...", station_id=station_id)
          return [dict(record) for record in result]
  ```

## Agreed Relational Schema

<!-- ============================================================
  FILL THIS IN after your team completes the schema design workshop.
  Paste your final CREATE TABLE statements here.
  ============================================================ -->

```sql
-- TODO: paste your final schema.sql contents here after team review
```

## Agreed Graph Schema

<!-- ============================================================
  FILL THIS IN after your team agrees on Neo4j node labels and
  relationship types.
  ============================================================ -->

```
Node labels:
- TODO

Relationship types:
- TODO

Key properties:
- TODO
```

## Function Signatures We Are Implementing

These are fixed contracts. AI-generated code must match these signatures exactly.

### Relational (`databases/relational/queries.py`)

```python
# Read-only
def query_national_rail_availability(origin_id: str, destination_id: str, travel_date: Optional[str] = None) -> list[dict]: ...
def query_national_rail_fare(schedule_id: str, fare_class: str, stops_travelled: int) -> Optional[dict]: ...
def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]: ...
def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]: ...
def query_available_seats(schedule_id: str, travel_date: str, fare_class: str) -> list[dict]: ...
def query_user_profile(user_email: str) -> Optional[dict]: ...
def query_user_bookings(user_email: str) -> dict: ...  # returns {"national_rail": [...], "metro": [...]}
def query_payment_info(booking_id: str) -> Optional[dict]: ...

# Write operations
def execute_booking(user_id, schedule_id, origin_station_id, destination_station_id, travel_date, fare_class, seat_id, ticket_type="single") -> tuple[bool, dict | str]: ...
def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]: ...

# Auth
def register_user(email, first_name, surname, year_of_birth, password, secret_question, secret_answer) -> tuple[bool, str]: ...
def login_user(email: str, password: str) -> Optional[dict]: ...
def get_user_secret_question(email: str) -> Optional[str]: ...
def verify_secret_answer(email: str, answer: str) -> bool: ...
def update_password(email: str, new_password: str) -> bool: ...
```

### Graph (`databases/graph/queries.py`)

```python
def query_shortest_route(origin_id: str, destination_id: str, network: str = "auto") -> dict: ...
def query_cheapest_route(origin_id: str, destination_id: str, network: str = "auto", fare_class: str = "standard") -> dict: ...
def query_alternative_routes(origin_id, destination_id, avoid_station_id, network="auto", max_routes=3) -> list[list[dict]]: ...
def query_interchange_path(origin_id: str, destination_id: str) -> dict: ...
def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]: ...
def query_station_connections(station_id: str) -> list[dict]: ...
```

## Function Specification References

每個函式都有對應的詳細實作指南（`docs/` 目錄）。**產生程式碼前請先查閱對應文件**，文件中有完整的 SQL 偽代碼、回傳格式範例、快取 key 格式與驗收測試說明。

| 函式 | 實作指南 | 前置文件 |
|---|---|---|
| `query_national_rail_availability` | [docs/07](docs/07-A-query-nr-availability.md) | 04, 05 |
| `query_national_rail_fare` | [docs/08](docs/08-A-query-nr-fare-metro-schedules.md) | 04, 05 |
| `query_metro_schedules` | [docs/08](docs/08-A-query-nr-fare-metro-schedules.md) | 04, 05 |
| `query_metro_fare` | [docs/09](docs/09-A-query-metro-fare-seats.md) | 04, 05 |
| `query_available_seats` | [docs/09](docs/09-A-query-metro-fare-seats.md) | 04, 05 |
| `auto_select_adjacent_seats` | [docs/09](docs/09-A-query-metro-fare-seats.md) | — |
| `query_user_profile` / `query_user_bookings` / `query_payment_info` | [docs/06](docs/06-A-query-user-profile-bookings.md) | 04, 05 |
| `execute_booking` | [docs/10](docs/10-A-execute-booking.md) | 05, query_available_seats |
| `execute_cancellation` | [docs/11](docs/11-A-execute-cancellation.md) | 05, execute_booking |
| Auth functions | [docs/12](docs/12-A-auth-functions.md) | 04 |
| Neo4j seed scripts | [docs/13](docs/13-B-neo4j-seed-stations.md)–[15](docs/15-B-neo4j-seed-interchange.md) | Graph schema |
| `query_shortest_route` / `query_station_connections` | [docs/16](docs/16-B-query-shortest-route.md) | 13–15 seeded |
| `query_alternative_routes` | [docs/17](docs/17-B-query-alternative-routes.md) | 13–15 seeded |
| `query_interchange_path` | [docs/18](docs/18-B-query-interchange-path.md) | 13–15 seeded |
| `query_delay_ripple` | [docs/19](docs/19-B-query-delay-ripple.md) | 13–15 seeded |
| `query_cheapest_route` | [docs/20](docs/20-B-query-cheapest-route.md) | 13–15 seeded + 08, 09 |
| Stage 3 infrastructure | [docs/23](docs/23-stage3.1-exception-layer.md)–[26](docs/26-stage3.4-ui-observability.md) | Stage 1/2 complete |

---

## ⚠️ Critical Rules — 絕對不可違反

1. **禁止修改這三個檔案**：`skeleton/config.py`、`skeleton/llm_provider.py`、`skeleton/seed_vectors.py`
2. **Stage 1/2 禁止 import 快取**：`queries.py` 不得有 `from skeleton.cache import ...`，Stage 3.3 前一律不加快取邏輯
3. **絕對不快取這兩個函式**：`query_available_seats`、`execute_booking`（防止超賣）
4. **Neo4j 種子腳本用 `MERGE`，不用 `CREATE`**（確保可重入執行）
5. **`skeleton/agent.py` 禁止直接 import DB**：不可有 `import psycopg2`、`from neo4j`、`from databases.relational.queries import`、`from databases.graph.queries import`
6. **所有 SQL 輸入使用 `%s` placeholder**，嚴禁字串格式化 SQL
7. **主軸 B 開始前必須清理 scaffold**：刪除 `databases/graph/queries.py` 頂部的 `from neo4j import GraphDatabase` 與 `def _driver():` 兩段代碼
8. **寫入操作需手動管理 `autocommit=False`**；讀取操作使用 `_connect()`（已設定 autocommit=True）

---

## ⛔ AI 常見錯誤 — 禁止以下模式

```python
# ❌ 錯誤簽名（舊版已廢棄，請勿使用）
query_national_rail_fare(origin_id, destination_id, fare_class)
#   → 正確：query_national_rail_fare(schedule_id, fare_class, stops_travelled)

query_metro_fare(origin_id, destination_id)
#   → 正確：query_metro_fare(schedule_id, stops_travelled)

query_metro_schedules(line_id, direction, travel_date)
#   → 正確：query_metro_schedules(origin_id, destination_id)

# ❌ query_metro_fare 中做圖遍歷 / BFS
#   → 正確：只查 metro_schedules 確認 schedule_id 存在，再依 stops_travelled 分層計費

# ❌ 直接以站點 ID 呼叫票價函式（query_cheapest_route 中）
fare_info = query_metro_fare(from_id, to_id)
#   → 正確兩步模式：
metro_scheds = query_metro_schedules(from_id, to_id)
fare_info    = query_metro_fare(metro_scheds[0]["schedule_id"], stops_travelled)

fare_info = query_national_rail_fare(from_id, to_id, fare_class)
#   → 正確兩步模式：
avail     = query_national_rail_availability(from_id, to_id)
fare_info = query_national_rail_fare(avail[0]["schedule_id"], fare_class, stops_travelled)

# ❌ Stage 1/2 中在 queries.py 加入快取 import
from skeleton.cache import fare_cache   # Stage 3.3 之前禁止

# ❌ 使用不存在的表格名稱（只能用 schema.sql 定義的名稱）
SELECT * FROM fares ...        # 表格不存在
SELECT * FROM stations ...     # 表格不存在
SELECT * FROM metro_station_adjacencies ...  # 此表格已棄用（metro_fare 不再依賴它）
```

**快取 key 格式參考**（Stage 3.3 實作時使用）：
- `query_national_rail_fare` → `"fare:{schedule_id}:{fare_class}:{stops_travelled}"`
- `query_metro_schedules` → `"metro_sched:{origin_id}:{destination_id}"`

---

## Team Decisions Log

<!-- Add entries as you make decisions. Format: "Decision: X. Why: Y." -->

- [ ] Schema design: TODO — add your table/column decisions here
- [ ] Graph schema: TODO — add your node label and relationship type decisions here
- [ ] (example) Metro schedule stop ordering: using `jsonb_array_elements` approach — easier to debug than containment operators

## Prompts That Worked

<!-- Share prompts that produced good output so teammates can reuse them. -->

### Schema design prompt that worked:
```
TODO — add a prompt here after your schema design workshop
```

### Query implementation prompt that worked:
```
TODO — add after implementing your first function
```
