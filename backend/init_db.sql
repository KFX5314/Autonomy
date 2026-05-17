-- ============================================================
-- TFG-DEMENCIA: MariaDB canonical schema
-- ============================================================
-- This script is intentionally resettable for the final academic delivery.
-- It drops the local development database and recreates the complete schema.
--
-- Run from the project root:
--   mariadb -u root -p < backend/init_db.sql
--
-- Or via Docker:
--   docker exec -i mariadb mariadb -u root -prootpass < backend/init_db.sql
-- ============================================================

DROP DATABASE IF EXISTS tfg_demencia;
CREATE DATABASE tfg_demencia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE OR REPLACE USER 'tfg_app'@'localhost'
  IDENTIFIED VIA mysql_native_password
  USING PASSWORD('tfg_pass_2024');
CREATE OR REPLACE USER 'tfg_app'@'127.0.0.1'
  IDENTIFIED VIA mysql_native_password
  USING PASSWORD('tfg_pass_2024');

GRANT ALL PRIVILEGES ON tfg_demencia.* TO 'tfg_app'@'localhost';
GRANT ALL PRIVILEGES ON tfg_demencia.* TO 'tfg_app'@'127.0.0.1';
FLUSH PRIVILEGES;

USE tfg_demencia;

-- ============================================================
-- USERS
-- ============================================================
-- Caregivers authenticate with email.
-- Patients authenticate with username because they may not have email.
-- role controls which identifier is valid.
-- ============================================================
CREATE TABLE users (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    email           VARCHAR(255)    NULL UNIQUE COMMENT 'Required for caregivers; NULL for patients',
    username        VARCHAR(64)     NULL UNIQUE COMMENT 'Required for patients; NULL for caregivers',
    password_hash   VARCHAR(255)    NOT NULL,
    full_name       VARCHAR(255)    NOT NULL,
    role            ENUM('caregiver','patient') NOT NULL,
    caregiver_id    BIGINT          NULL COMMENT 'Only for role=patient: FK to their caregiver',
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_caregiver FOREIGN KEY (caregiver_id) REFERENCES users(id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_users_role_identifier CHECK (
        (
            role = 'caregiver'
            AND email IS NOT NULL
            AND username IS NULL
            AND caregiver_id IS NULL
        )
        OR
        (
            role = 'patient'
            AND email IS NULL
            AND username IS NOT NULL
            AND caregiver_id IS NOT NULL
        )
    )
);

-- ============================================================
-- PATIENTS
-- ============================================================
-- One-to-one extended profile for users where role='patient'.
-- voice_embedding stores the current multi-sample shape:
--   {"samples": [{"id": "...", "embedding": [...], "active": true, ...}]}
-- ============================================================
CREATE TABLE patients (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL UNIQUE,
    voice_embedding JSON            NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_patient_user FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
);

-- ============================================================
-- PATIENT_CONTEXT
-- ============================================================
-- Flexible caregiver-owned context. New records use alert_phrases as the
-- unified deterministic phrase/regex list.
-- ============================================================
CREATE TABLE patient_context (
    patient_id      BIGINT          PRIMARY KEY,
    context_json    JSON            NOT NULL,
    updated_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_context_patient FOREIGN KEY (patient_id) REFERENCES patients(id)
        ON DELETE CASCADE
);

-- ============================================================
-- PUSH_TOKENS
-- ============================================================
CREATE TABLE push_tokens (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL,
    token           VARCHAR(255)    NOT NULL UNIQUE,
    platform        VARCHAR(32)     NULL,
    device_id       VARCHAR(128)    NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_push_user FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    INDEX idx_push_user (user_id)
);

-- ============================================================
-- TRANSCRIPTS
-- ============================================================
-- Stored transcription results from audio chunks.
-- Audio files are not stored by default; only alert-triggering chunks may be
-- archived separately under the configured alert audio directory.
-- ============================================================
CREATE TABLE transcripts (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    patient_id      BIGINT          NOT NULL,
    started_at      DATETIME        NOT NULL,
    ended_at        DATETIME        NOT NULL,
    lang            VARCHAR(8)      DEFAULT 'es',
    transcript_text TEXT            NOT NULL,
    stt_model       VARCHAR(64)     NOT NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_transcript_patient FOREIGN KEY (patient_id) REFERENCES patients(id)
        ON DELETE CASCADE,
    INDEX ix_transcript_patient_started (patient_id, started_at)
);

-- ============================================================
-- ALERTS
-- ============================================================
CREATE TABLE alerts (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    patient_id      BIGINT          NOT NULL,
    transcript_id   BIGINT          NULL,
    severity        SMALLINT        NOT NULL,
    reason          VARCHAR(512)    NOT NULL,
    llm_response    TEXT            NULL COMMENT 'Text generated by LLM for the patient',
    status          ENUM('NEW','ACK') DEFAULT 'NEW',
    audio_path      VARCHAR(512)    NULL COMMENT 'Archived alert audio path, cleared on ACK/retention',
    acknowledged_at TIMESTAMP       NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_alert_patient FOREIGN KEY (patient_id) REFERENCES patients(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_alert_transcript FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
        ON DELETE SET NULL,
    CONSTRAINT ck_alert_severity CHECK (severity BETWEEN 1 AND 5),
    INDEX idx_alert_patient_status (patient_id, status)
);

-- ============================================================
-- JOURNAL_ENTRIES
-- ============================================================
-- Long-term memory entries generated asynchronously from recent transcripts.
-- ============================================================
CREATE TABLE journal_entries (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    patient_id      BIGINT          NOT NULL,
    covers_start    DATETIME        NOT NULL,
    covers_end      DATETIME        NOT NULL,
    summary_text    VARCHAR(500)    NOT NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_journal_patient FOREIGN KEY (patient_id) REFERENCES patients(id)
        ON DELETE CASCADE,
    INDEX ix_journal_patient_created (patient_id, created_at)
);

SELECT 'OK: tfg_demencia reset and schema ready' AS result;
