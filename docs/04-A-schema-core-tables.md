# 04 — 主軸 A｜PostgreSQL 基礎資料表 DDL

> **前置條件**：無（本任務為 A 主軸第一步）
> **後續任務**：`05-A-schema-transit-tables.md`

---

## 任務目標

在 `databases/relational/schema.sql` 中，設計並撰寫以下四張基礎資料表的 DDL：
`users`、`metro_stations`、`national_rail_stations`、`metro_station_adjacencies`。
這四張表構成整個 PostgreSQL 模式的根基，所有其他資料表皆依賴它們。

---

## 介面規格

**目標檔案**：`databases/relational/schema.sql`（第一部分）

### 資料表一：`users`

```
主鍵：user_id VARCHAR(20)
必要欄位：
  full_name       VARCHAR(100) NOT NULL
  email           VARCHAR(255) NOT NULL UNIQUE
  phone           VARCHAR(20)（可空）
  date_of_birth   DATE（可空）
  registered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
  is_active       BOOLEAN NOT NULL DEFAULT true
  password        VARCHAR(255)（儲存 Argon2id 雜湊，由應用層填入）
  secret_question VARCHAR(500)
  secret_answer   VARCHAR(255)

約束條件（CONSTRAINT 名稱需明確）：
  chk_email_format    → 使用正規表達式驗證 email 格式（RFC 5322 簡化版）
  chk_dob_valid       → date_of_birth < CURRENT_DATE
  chk_registered_time → registered_at <= NOW()
```

### 資料表二：`metro_stations`

```
主鍵：metro_station_id VARCHAR(20)
必要欄位：
  name                               VARCHAR(100) NOT NULL
  lines                              JSONB NOT NULL DEFAULT '[]'
  is_interchange_metro               BOOLEAN NOT NULL DEFAULT false
  is_interchange_national_rail       BOOLEAN NOT NULL DEFAULT false
  interchange_national_rail_station_id VARCHAR(20)（可空，外鍵至 national_rail_stations，延遲驗證）

約束條件：
  chk_interchange_national_rail_consistency
    → NOT is_interchange_national_rail OR interchange_national_rail_station_id IS NOT NULL
```

### 資料表三：`national_rail_stations`

```
主鍵：national_rail_station_id VARCHAR(20)
必要欄位：
  name                        VARCHAR(100) NOT NULL
  lines                       JSONB NOT NULL DEFAULT '[]'
  is_interchange_national_rail BOOLEAN NOT NULL DEFAULT false
  is_interchange_metro        BOOLEAN NOT NULL DEFAULT false
  interchange_metro_station_id VARCHAR(20)（可空，外鍵至 metro_stations，延遲驗證）

約束條件：
  chk_interchange_metro_consistency
    → NOT is_interchange_metro OR interchange_metro_station_id IS NOT NULL
```

**重要設計注意**：`metro_stations` 與 `national_rail_stations` 互相外鍵引用（循環依賴），
必須使用 `DEFERRABLE INITIALLY DEFERRED` 延遲約束，或在資料表建立後使用 `ALTER TABLE ADD CONSTRAINT` 附加外鍵。

### 資料表四：`metro_station_adjacencies`

```
主鍵：adjacency_id SERIAL
必要欄位：
  origin_station_id      VARCHAR(20) NOT NULL → FK → metro_stations.metro_station_id
  destination_station_id VARCHAR(20) NOT NULL → FK → metro_stations.metro_station_id
  line                   VARCHAR(20) NOT NULL（例：'M1'）
  travel_time_min        INTEGER NOT NULL DEFAULT 1
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()

約束條件：
  chk_adjacency_no_self_loop → origin_station_id <> destination_station_id
  uq_adjacency_unique        → UNIQUE(origin_station_id, destination_station_id, line)

外鍵行為：ON DELETE CASCADE ON UPDATE CASCADE（站點刪除時鄰接關係同步刪除）
```

> ⚠️ **種子資料說明（`seed_postgres.py` 必做）**
>
> `metro_station_adjacencies` 的資料來源是 `train-mock-data/metro_stations.json` 中
> 每個站點物件的 `adjacent_stations` 欄位，格式為：
> `[{station_id: "MS02", line: "M1", travel_time_min: 3}, ...]`
>
> 實作 `seed_postgres.py` 時，必須**另外加入** `seed_metro_station_adjacencies(cur)` 函式，
> 並在 `main()` 的 `seed_metro_stations(cur)` 之後立即呼叫（外鍵依賴順序）：
>
> ```
> seed_metro_stations(cur)
> seed_metro_station_adjacencies(cur)   ← 不可缺少
> seed_national_rail_stations(cur)
> ...
> ```
>
> **若略過此步驟**，`query_metro_fare` 的 BFS 演算法將查詢不到任何鄰接關係，
> 導致所有捷運票價整合測試（`test_phase_1.2.1.6_query_metro_fare.py`）失敗。
> 報錯訊息只會顯示「BFS 回傳 0 跳 / fare_usd 計算異常」，
> **不會直接指出「鄰接表是空的」** 才是根本原因，排查成本很高。

---

## 實作邏輯導引

### 步驟一：冪等清理層（DROP IF EXISTS）

在 schema.sql 開頭加入 DROP 語句，確保腳本可以重複執行而不報錯。
刪除順序需遵循**外鍵依賴的反向順序**，即先刪除依賴表（如 payments），最後刪除被依賴的根表（如 users）。
使用 `CASCADE` 關鍵字確保相關外鍵約束同步刪除。

```
偽代碼：
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS metro_travel_history CASCADE;
DROP TABLE IF EXISTS national_rail_bookings CASCADE;
... （按依賴反向順序）
DROP TABLE IF EXISTS metro_stations CASCADE;
DROP TABLE IF EXISTS national_rail_stations CASCADE;
DROP TABLE IF EXISTS users CASCADE;
```

### 步驟二：建立 users 表

直接建立，無外鍵依賴。
用 `CREATE TABLE IF NOT EXISTS` 確保幂等性。
注意 `CHECK` 約束使用 `CONSTRAINT <名稱> CHECK (條件)` 格式，名稱要有語義。
email 正規表達式使用 `~` 運算子（PostgreSQL 的正規表達式匹配運算子）。

### 步驟三：建立 metro_stations 和 national_rail_stations（處理循環外鍵）

**問題**：metro_stations 需要外鍵指向 national_rail_stations，反之亦然。
**解法**：先建立兩張表（不含跨表外鍵），再用 `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... DEFERRABLE INITIALLY DEFERRED` 加入延遲外鍵。

建立順序：
1. 先建立 `national_rail_stations`（不含 interchange_metro FK）
2. 再建立 `metro_stations`（不含 interchange_national_rail FK）
3. 使用兩個 `ALTER TABLE` 語句各加入一個延遲外鍵

延遲外鍵語法關鍵字：`DEFERRABLE INITIALLY DEFERRED`
— 這讓同一交易中的循環插入成為可能（先插入 A 再插入 B，在 COMMIT 時才驗證外鍵）

### 步驟四：建立 metro_station_adjacencies

此表引用 metro_stations 兩次（origin 和 destination），兩個 FK 都指向同一張表。
自身迴圈防護：使用 `CHECK (origin_station_id <> destination_station_id)` 防止站點指向自己。
複合唯一約束：`UNIQUE(origin_station_id, destination_station_id, line)` 防止重複鄰接關係（但同兩站點可以在不同 line 上有不同關係）。

---

## 驗收標準

**驗收測試**：
Schema 正確後，執行完整測試套件確認基礎結構無誤：

**手動驗證指令**：
```sql
-- 確認表結構正確
\d users
\d metro_stations
\d national_rail_stations
\d metro_station_adjacencies

-- 確認循環外鍵存在
SELECT conname, contype FROM pg_constraint WHERE conrelid = 'metro_stations'::regclass;
```

**通過條件**：
1. `schema.sql` 可完整執行，不報錯
2. `python skeleton/seed_postgres.py` 可成功插入種子資料（使用者、站點）
3. `pytest tests/unit/ -k "user" -v` 全數通過
