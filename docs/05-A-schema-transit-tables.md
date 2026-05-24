# 05 — 主軸 A｜PostgreSQL 交通業務資料表 DDL + 索引 + pgvector

> **前置條件**：`04-A-schema-core-tables.md` 完成（`users`、站點、鄰接表已建立）
> **後續任務**：`06` 到 `12`（所有關聯式查詢函式均依賴本任務的表結構）

---

## 任務目標

在 `databases/relational/schema.sql` 的第二部分，建立以下五張業務核心表，並加入全部效能索引與 pgvector 擴充。

---

## 介面規格

### 資料表五：`metro_schedules`

```
主鍵：schedule_id VARCHAR(30)
必要欄位：
  line                    VARCHAR(20) NOT NULL（如 'M1', 'M2'）
  direction               VARCHAR(20) NOT NULL（如 'northbound', 'southbound'）
  origin_station_id       VARCHAR(20) NOT NULL → FK → metro_stations.metro_station_id
  destination_station_id  VARCHAR(20) NOT NULL → FK → metro_stations.metro_station_id
  first_train_time        TIME NOT NULL
  last_train_time         TIME NOT NULL
  base_fare_usd           NUMERIC(8,2) NOT NULL
  operating_days          JSONB NOT NULL DEFAULT '["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]'
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()

約束條件：
  chk_base_fare_positive   → base_fare_usd > 0
  chk_metro_time_logic     → first_train_time < last_train_time
  chk_metro_stations_differ → origin_station_id <> destination_station_id
```

### 資料表六：`national_rail_schedules`

```
主鍵：schedule_id VARCHAR(30)
必要欄位：
  line                    VARCHAR(20) NOT NULL
  service_type            VARCHAR(20) NOT NULL（'normal', 'express', 'delayed'）
  direction               VARCHAR(20) NOT NULL
  origin_station_id       VARCHAR(20) NOT NULL → FK → national_rail_stations
  destination_station_id  VARCHAR(20) NOT NULL → FK → national_rail_stations
  first_train_time        TIME NOT NULL
  last_train_time         TIME NOT NULL
  base_fare_usd           NUMERIC(8,2) NOT NULL
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()

約束條件：同 metro_schedules，名稱前綴改為 chk_national_rail_*
```

### 資料表七：`national_rail_seat_layouts`

```
主鍵：layout_id VARCHAR(30)
必要欄位：
  schedule_id   VARCHAR(30) NOT NULL → FK → national_rail_schedules（ON DELETE CASCADE）
  coaches       JSONB NOT NULL DEFAULT '{}'
  total_seats   INTEGER NOT NULL
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()

約束條件：
  chk_total_seats_positive → total_seats > 0

JSONB 結構規格（coaches 欄位的巢狀格式）：
  [
    {
      "coach": "A",
      "fare_class": "standard",
      "seats": [
        {"seat_id": "A01", "row": 1, "column": "A"},
        {"seat_id": "A02", "row": 1, "column": "B"},
        ...
      ]
    },
    {
      "coach": "D",
      "fare_class": "first",
      "seats": [...]
    }
  ]
```

### 資料表八：`national_rail_bookings`

```
主鍵：booking_id VARCHAR(30)
必要欄位：
  user_id                 VARCHAR(20) NOT NULL → FK → users（ON DELETE RESTRICT）
  schedule_id             VARCHAR(30) NOT NULL → FK → national_rail_schedules（ON DELETE RESTRICT）
  origin_station_id       VARCHAR(20) NOT NULL → FK → national_rail_stations（ON DELETE RESTRICT）
  destination_station_id  VARCHAR(20) NOT NULL → FK → national_rail_stations（ON DELETE RESTRICT）
  travel_date             DATE NOT NULL
  departure_time          TIME NOT NULL
  ticket_type             VARCHAR(20) NOT NULL（'single', 'return', 'pass'）
  fare_class              VARCHAR(20) NOT NULL（'standard', 'first', 'senior', 'student'）
  coach                   VARCHAR(10)（可空）
  seat_id                 VARCHAR(20)（可空）
  amount_usd              NUMERIC(8,2) NOT NULL
  status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
  booked_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
  travelled_at            TIMESTAMPTZ（可空）
  cancelled_at            TIMESTAMPTZ（可空）
  cancellation_reason     VARCHAR(500)（可空）

約束條件：
  chk_booking_amount_positive          → amount_usd > 0
  chk_booking_travelled_after_booked   → travelled_at IS NULL OR travelled_at >= booked_at
  chk_booking_cancelled_consistency    → (status <> 'cancelled') OR (cancelled_at IS NOT NULL)
  chk_booking_status_valid             → status IN ('pending','confirmed','completed','cancelled')
```

### 資料表九：`metro_travel_history`

```
主鍵：trip_id VARCHAR(30)
必要欄位：
  user_id                 VARCHAR(20) NOT NULL → FK → users
  schedule_id             VARCHAR(30) NOT NULL → FK → metro_schedules
  origin_station_id       VARCHAR(20) NOT NULL → FK → metro_stations
  destination_station_id  VARCHAR(20) NOT NULL → FK → metro_stations
  travel_date             DATE NOT NULL
  ticket_type             VARCHAR(20) NOT NULL
  amount_usd              NUMERIC(8,2) NOT NULL
  status                  VARCHAR(20) NOT NULL DEFAULT 'completed'
  purchased_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
  travelled_at            TIMESTAMPTZ（可空）

約束條件：
  chk_metro_amount_positive          → amount_usd > 0
  chk_metro_travelled_after_purchased → travelled_at IS NULL OR travelled_at >= purchased_at
  chk_metro_status_valid             → status IN ('completed','cancelled','refunded')
```

### 資料表十：`payments`

```
主鍵：payment_id VARCHAR(30)
必要欄位：
  booking_id  VARCHAR(30) NOT NULL（文字外鍵，跨表引用，不設資料庫外鍵約束）
  amount_usd  NUMERIC(8,2) NOT NULL
  method      VARCHAR(30) NOT NULL（'credit_card','debit_card','ewallet','cancellation'）
  status      VARCHAR(20) NOT NULL DEFAULT 'paid'
  paid_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
  refunded_at TIMESTAMPTZ（可空）

約束條件：
  chk_payment_amount_positive    → amount_usd > 0
  chk_payment_status_valid       → status IN ('paid','refunded','pending','failed')
  chk_payment_refund_consistency → (status <> 'refunded') OR (refunded_at IS NOT NULL)

注意：payments.booking_id 刻意不設外鍵約束，
因為它同時引用 national_rail_bookings 和 metro_travel_history 兩張表（多態關聯）。
```

---

## 索引規格（19 個效能索引）

### 使用者表索引

```
idx_users_email  → ON users(email)  —— 認證登入 O(log n) 查詢
idx_users_phone  → ON users(phone)  —— 電話號碼查詢
```

### 捷運站點索引

```
idx_metro_stations_name   → ON metro_stations(name)
idx_metro_stations_lines  → ON metro_stations USING gin(lines)  —— JSONB @> 查詢需要 GIN 索引
```

### 國鐵站點索引

```
idx_national_rail_stations_name   → ON national_rail_stations(name)
idx_national_rail_stations_lines  → ON national_rail_stations USING gin(lines)
```

### 時刻表索引

```
idx_metro_schedules_line          → ON metro_schedules(line)
idx_metro_schedules_route         → ON metro_schedules(origin_station_id, destination_station_id)
idx_national_rail_schedules_line  → ON national_rail_schedules(line)
idx_national_rail_schedules_route → ON national_rail_schedules(origin_station_id, destination_station_id)
```

### 訂票紀錄索引

```
idx_national_rail_bookings_user_id     → ON national_rail_bookings(user_id)
idx_national_rail_bookings_travel_date → ON national_rail_bookings(travel_date)
idx_national_rail_bookings_schedule_id → ON national_rail_bookings(schedule_id)
```

### 捷運旅遊歷史索引

```
idx_metro_travel_history_user_id     → ON metro_travel_history(user_id)
idx_metro_travel_history_travel_date → ON metro_travel_history(travel_date)
idx_metro_travel_history_schedule_id → ON metro_travel_history(schedule_id)
```

### 付款索引

```
idx_payments_booking_id → ON payments(booking_id)
idx_payments_status     → ON payments(status)
idx_payments_paid_at    → ON payments(paid_at)
```

---

## pgvector 擴充與 policy_documents 表

### 擴充啟用

```sql
-- 必須在建立 policy_documents 之前執行
CREATE EXTENSION IF NOT EXISTS vector;
```

### policy_documents 資料表（不得修改欄位名稱）

```
主鍵：id SERIAL
欄位：
  title       VARCHAR(200) NOT NULL
  category    VARCHAR(50) NOT NULL（'refund','booking','conduct','ticket_types'）
  content     TEXT NOT NULL
  embedding   vector(768)（預設 Ollama 維度；改用 Gemini 需改為 vector(3072)）
  source_file VARCHAR(200)
  created_at  TIMESTAMPTZ DEFAULT NOW()
```

### 向量索引（HNSW，餘弦相似度）

```
idx_policy_documents_embedding
→ ON policy_documents USING hnsw (embedding vector_cosine_ops)

效能說明：HNSW（Hierarchical Navigable Small World）索引對高維向量的
近似近鄰搜尋（ANN）有 O(log n) 的查詢效率，是 pgvector 的推薦索引。
```

---

## 實作邏輯導引

### 關鍵邏輯一：JSONB 欄位的預設值語法

PostgreSQL 的 JSONB 預設值必須是字串字面量，需加上明確的型別轉換：
```
DEFAULT '["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]'::jsonb
```

### 關鍵邏輯二：外鍵行為選擇

本模式各表的外鍵刪除行為設計：
- 時刻表（schedules）→ 站點（stations）：`ON DELETE RESTRICT`（禁止刪除有班次的站點）
- 座位佈局（seat_layouts）→ 班次（schedules）：`ON DELETE CASCADE`（班次刪除後，佈局同步刪除）
- 訂票（bookings）→ 班次 / 使用者 / 站點：`ON DELETE RESTRICT`（保護歷史訂票資料）
- 旅遊歷史（metro_travel_history）→ 相關表：`ON DELETE RESTRICT`

### 關鍵邏輯三：payments 的多態設計

`payments.booking_id` 引用的可能是 `national_rail_bookings.booking_id`（格式 "BK-XXXXXX"）
或 `metro_travel_history.trip_id`（格式 "MT001"）。
因此不可設 PostgreSQL 原生外鍵——這是一個已知的設計取捨（trade-off）。

### 關鍵邏輯四：CREATE INDEX IF NOT EXISTS

所有索引使用 `IF NOT EXISTS` 確保重複執行 schema.sql 不會報錯。

---

## 驗收標準

**驗收測試**：
種子資料腳本成功執行後，再執行測試套件：
- `python skeleton/seed_postgres.py`（不報錯）

**手動驗證**：
```sql
-- 確認所有表都存在
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
-- 預期：metro_schedules, metro_stations, metro_station_adjacencies,
--        metro_travel_history, national_rail_bookings, national_rail_schedules,
--        national_rail_seat_layouts, national_rail_stations,
--        payments, policy_documents, users

-- 確認 pgvector 擴充啟用
SELECT * FROM pg_extension WHERE extname = 'vector';

-- 確認索引數量（至少 19 個業務索引 + 1 個向量索引）
SELECT count(*) FROM pg_indexes WHERE tablename IN (
  'users','metro_stations','national_rail_stations','metro_schedules',
  'national_rail_schedules','national_rail_bookings','metro_travel_history','payments'
);
```
