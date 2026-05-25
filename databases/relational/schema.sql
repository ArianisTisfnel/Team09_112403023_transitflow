-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  RELATIONAL SCHEMA — 主軸 A 實作
-- ============================================================

-- ------------------------------------------------------------
--  冪等清理層（DROP IF EXISTS）— 依外鍵依賴反向順序
-- ------------------------------------------------------------
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

-- ------------------------------------------------------------
--  Table 1: users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
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

-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,
    content     TEXT         NOT NULL,
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);