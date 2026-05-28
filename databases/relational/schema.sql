-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  刪除策略說明（Delete Strategy）
--  核心資料表（users, stations）使用 ON DELETE RESTRICT，
--  防止誤刪有關聯資料的記錄，保護歷史訂票與使用者資料的完整性。
--  依賴資料表（seat_layouts）使用 ON DELETE CASCADE，
--  父資料刪除時子資料同步清除，避免孤立記錄。
--  統一使用硬刪除（hard delete），不使用軟刪除，
--  因為本系統不需要保留已刪除記錄的查詢功能。
-- ============================================================

-- ============================================================
--  冪等清理層（DROP IF EXISTS）— 依外鍵依賴反向順序
-- ============================================================
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS metro_travel_history CASCADE;
DROP TABLE IF EXISTS national_rail_bookings CASCADE;
DROP TABLE IF EXISTS national_rail_seat_layouts CASCADE;
DROP TABLE IF EXISTS national_rail_schedules CASCADE;
DROP TABLE IF EXISTS metro_schedules CASCADE;
DROP TABLE IF EXISTS metro_station_adjacencies CASCADE;
DROP TABLE IF EXISTS metro_stations CASCADE;
DROP TABLE IF EXISTS national_rail_stations CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS policy_documents CASCADE;

-- ============================================================
--  RELATIONAL SCHEMA — 主軸 A 實作
-- ============================================================

-- ------------------------------------------------------------
--  Table 1: users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    -- PK 設計說明：使用 VARCHAR(20) 作為主鍵（如 "RU01"），而非 UUID 或 SERIAL。
    -- 原因：業務層需要可讀性高的 ID（方便 debug 與 agent 呼叫），
    -- 且資料量不大，VARCHAR 的查詢效能足夠。
    user_id         VARCHAR(20)  PRIMARY KEY,
    full_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone           VARCHAR(20),
    date_of_birth   DATE,
    registered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    password        VARCHAR(255),
    secret_question VARCHAR(500),
    secret_answer   VARCHAR(255),
    CONSTRAINT chk_email_format    CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    CONSTRAINT chk_dob_valid       CHECK (date_of_birth < CURRENT_DATE),
    CONSTRAINT chk_registered_time CHECK (registered_at <= NOW())
);

-- ------------------------------------------------------------
--  Table 2 & 3: national_rail_stations + metro_stations
--  （先建立兩張表，再用 ALTER TABLE 加入循環外鍵）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS national_rail_stations (
    national_rail_station_id     VARCHAR(20)  PRIMARY KEY,
    name                         VARCHAR(100) NOT NULL,
    lines                        JSONB        NOT NULL DEFAULT '[]',
    is_interchange_national_rail BOOLEAN      NOT NULL DEFAULT false,
    is_interchange_metro         BOOLEAN      NOT NULL DEFAULT false,
    interchange_metro_station_id VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS metro_stations (
    metro_station_id                     VARCHAR(20)  PRIMARY KEY,
    name                                 VARCHAR(100) NOT NULL,
    lines                                JSONB        NOT NULL DEFAULT '[]',
    is_interchange_metro                 BOOLEAN      NOT NULL DEFAULT false,
    is_interchange_national_rail         BOOLEAN      NOT NULL DEFAULT false,
    interchange_national_rail_station_id VARCHAR(20),
    CONSTRAINT chk_interchange_national_rail_consistency
        CHECK (NOT is_interchange_national_rail OR interchange_national_rail_station_id IS NOT NULL)
);

-- 循環外鍵（延遲驗證）
ALTER TABLE national_rail_stations
    ADD CONSTRAINT fk_nr_interchange_metro
    FOREIGN KEY (interchange_metro_station_id)
    REFERENCES metro_stations(metro_station_id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE metro_stations
    ADD CONSTRAINT fk_metro_interchange_nr
    FOREIGN KEY (interchange_national_rail_station_id)
    REFERENCES national_rail_stations(national_rail_station_id)
    DEFERRABLE INITIALLY DEFERRED;

-- ------------------------------------------------------------
--  Table 4: metro_station_adjacencies
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metro_station_adjacencies (
    adjacency_id           SERIAL      PRIMARY KEY,
    origin_station_id      VARCHAR(20) NOT NULL,
    destination_station_id VARCHAR(20) NOT NULL,
    line                   VARCHAR(20) NOT NULL,
    travel_time_min        INTEGER     NOT NULL DEFAULT 1,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_adjacency_no_self_loop
        CHECK (origin_station_id <> destination_station_id),
    CONSTRAINT uq_adjacency_unique
        UNIQUE (origin_station_id, destination_station_id, line),
    CONSTRAINT fk_adjacency_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES metro_stations(metro_station_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_adjacency_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES metro_stations(metro_station_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- ------------------------------------------------------------
--  Table 5: metro_schedules
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metro_schedules (
    schedule_id            VARCHAR(30) PRIMARY KEY,
    line                   VARCHAR(20) NOT NULL,
    direction              VARCHAR(20) NOT NULL,
    origin_station_id      VARCHAR(20) NOT NULL,
    destination_station_id VARCHAR(20) NOT NULL,
    first_train_time       TIME        NOT NULL,
    last_train_time        TIME        NOT NULL,
    base_fare_usd          NUMERIC(8,2) NOT NULL,
    operating_days         JSONB       NOT NULL DEFAULT '["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]'::jsonb,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_base_fare_positive    CHECK (base_fare_usd > 0),
    CONSTRAINT chk_metro_time_logic      CHECK (first_train_time < last_train_time),
    CONSTRAINT chk_metro_stations_differ CHECK (origin_station_id <> destination_station_id),
    CONSTRAINT fk_metro_schedule_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES metro_stations(metro_station_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_metro_schedule_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES metro_stations(metro_station_id)
        ON DELETE RESTRICT
);

-- ------------------------------------------------------------
--  Table 6: national_rail_schedules
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS national_rail_schedules (
    schedule_id            VARCHAR(30) PRIMARY KEY,
    line                   VARCHAR(20) NOT NULL,
    service_type           VARCHAR(20) NOT NULL,
    direction              VARCHAR(20) NOT NULL,
    origin_station_id      VARCHAR(20) NOT NULL,
    destination_station_id VARCHAR(20) NOT NULL,
    first_train_time       TIME        NOT NULL,
    last_train_time        TIME        NOT NULL,
    base_fare_usd          NUMERIC(8,2) NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_national_rail_base_fare_positive    CHECK (base_fare_usd > 0),
    CONSTRAINT chk_national_rail_time_logic            CHECK (first_train_time < last_train_time),
    CONSTRAINT chk_national_rail_stations_differ       CHECK (origin_station_id <> destination_station_id),
    CONSTRAINT fk_nr_schedule_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES national_rail_stations(national_rail_station_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_nr_schedule_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES national_rail_stations(national_rail_station_id)
        ON DELETE RESTRICT
);

-- ------------------------------------------------------------
--  Table 7: national_rail_seat_layouts
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS national_rail_seat_layouts (
    layout_id   VARCHAR(30) PRIMARY KEY,
    schedule_id VARCHAR(30) NOT NULL,
    coaches     JSONB       NOT NULL DEFAULT '{}',
    total_seats INTEGER     NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_total_seats_positive CHECK (total_seats > 0),
    CONSTRAINT fk_seat_layout_schedule
        FOREIGN KEY (schedule_id)
        REFERENCES national_rail_schedules(schedule_id)
        ON DELETE CASCADE
);

-- ------------------------------------------------------------
--  Table 8: national_rail_bookings
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS national_rail_bookings (
    booking_id             VARCHAR(30) PRIMARY KEY,
    user_id                VARCHAR(20) NOT NULL,
    schedule_id            VARCHAR(30) NOT NULL,
    origin_station_id      VARCHAR(20) NOT NULL,
    destination_station_id VARCHAR(20) NOT NULL,
    travel_date            DATE        NOT NULL,
    departure_time         TIME        NOT NULL,
    ticket_type            VARCHAR(20) NOT NULL,
    fare_class             VARCHAR(20) NOT NULL,
    coach                  VARCHAR(10),
    seat_id                VARCHAR(20),
    amount_usd             NUMERIC(8,2) NOT NULL,
    status                 VARCHAR(20) NOT NULL DEFAULT 'pending',
    booked_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    travelled_at           TIMESTAMPTZ,
    cancelled_at           TIMESTAMPTZ,
    cancellation_reason    VARCHAR(500),
    CONSTRAINT chk_booking_amount_positive
        CHECK (amount_usd > 0),
    CONSTRAINT chk_booking_travelled_after_booked
        CHECK (travelled_at IS NULL OR travelled_at >= booked_at),
    CONSTRAINT chk_booking_cancelled_consistency
        CHECK ((status <> 'cancelled') OR (cancelled_at IS NOT NULL)),
    CONSTRAINT chk_booking_status_valid
        CHECK (status IN ('pending','confirmed','completed','cancelled')),
    CONSTRAINT fk_booking_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_booking_schedule
        FOREIGN KEY (schedule_id)
        REFERENCES national_rail_schedules(schedule_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_booking_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES national_rail_stations(national_rail_station_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_booking_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES national_rail_stations(national_rail_station_id)
        ON DELETE RESTRICT
);

-- ------------------------------------------------------------
--  Table 9: metro_travel_history
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metro_travel_history (
    trip_id                VARCHAR(30) PRIMARY KEY,
    user_id                VARCHAR(20) NOT NULL,
    schedule_id            VARCHAR(30) NOT NULL,
    origin_station_id      VARCHAR(20) NOT NULL,
    destination_station_id VARCHAR(20) NOT NULL,
    travel_date            DATE        NOT NULL,
    ticket_type            VARCHAR(20) NOT NULL,
    amount_usd             NUMERIC(8,2) NOT NULL,
    status                 VARCHAR(20) NOT NULL DEFAULT 'completed',
    purchased_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    travelled_at           TIMESTAMPTZ,
    CONSTRAINT chk_metro_amount_positive
        CHECK (amount_usd > 0),
    CONSTRAINT chk_metro_travelled_after_purchased
        CHECK (travelled_at IS NULL OR travelled_at >= purchased_at),
    CONSTRAINT chk_metro_status_valid
        CHECK (status IN ('completed','cancelled','refunded')),
    CONSTRAINT fk_metro_history_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_metro_history_schedule
        FOREIGN KEY (schedule_id)
        REFERENCES metro_schedules(schedule_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_metro_history_origin
        FOREIGN KEY (origin_station_id)
        REFERENCES metro_stations(metro_station_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_metro_history_destination
        FOREIGN KEY (destination_station_id)
        REFERENCES metro_stations(metro_station_id)
        ON DELETE RESTRICT
);

-- ------------------------------------------------------------
--  Table 10: payments
--  （booking_id 刻意不設外鍵，因為同時引用兩張表）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    payment_id  VARCHAR(30) PRIMARY KEY,
    booking_id  VARCHAR(30) NOT NULL,
    amount_usd  NUMERIC(8,2) NOT NULL,
    method      VARCHAR(30) NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'paid',
    paid_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    refunded_at TIMESTAMPTZ,
    CONSTRAINT chk_payment_amount_positive
        CHECK (amount_usd > 0),
    CONSTRAINT chk_payment_status_valid
        CHECK (status IN ('paid','refunded','pending','failed')),
    CONSTRAINT chk_payment_refund_consistency
        CHECK ((status <> 'refunded') OR (refunded_at IS NOT NULL))
);

-- ============================================================
--  效能索引（19 個業務索引）
-- ============================================================

-- 使用者
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

-- 捷運站點
CREATE INDEX IF NOT EXISTS idx_metro_stations_name  ON metro_stations(name);
CREATE INDEX IF NOT EXISTS idx_metro_stations_lines ON metro_stations USING gin(lines);

-- 國鐵站點
CREATE INDEX IF NOT EXISTS idx_national_rail_stations_name  ON national_rail_stations(name);
CREATE INDEX IF NOT EXISTS idx_national_rail_stations_lines ON national_rail_stations USING gin(lines);

-- 時刻表
CREATE INDEX IF NOT EXISTS idx_metro_schedules_line          ON metro_schedules(line);
CREATE INDEX IF NOT EXISTS idx_metro_schedules_route         ON metro_schedules(origin_station_id, destination_station_id);
CREATE INDEX IF NOT EXISTS idx_national_rail_schedules_line  ON national_rail_schedules(line);
CREATE INDEX IF NOT EXISTS idx_national_rail_schedules_route ON national_rail_schedules(origin_station_id, destination_station_id);

-- 訂票紀錄
CREATE INDEX IF NOT EXISTS idx_national_rail_bookings_user_id     ON national_rail_bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_national_rail_bookings_travel_date ON national_rail_bookings(travel_date);
CREATE INDEX IF NOT EXISTS idx_national_rail_bookings_schedule_id ON national_rail_bookings(schedule_id);

-- 捷運旅遊歷史
CREATE INDEX IF NOT EXISTS idx_metro_travel_history_user_id     ON metro_travel_history(user_id);
CREATE INDEX IF NOT EXISTS idx_metro_travel_history_travel_date ON metro_travel_history(travel_date);
CREATE INDEX IF NOT EXISTS idx_metro_travel_history_schedule_id ON metro_travel_history(schedule_id);

-- 付款
CREATE INDEX IF NOT EXISTS idx_payments_booking_id ON payments(booking_id);
CREATE INDEX IF NOT EXISTS idx_payments_status     ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_paid_at    ON payments(paid_at);

-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,
    content     TEXT         NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_policy_documents_embedding
    ON policy_documents USING hnsw (embedding vector_cosine_ops);