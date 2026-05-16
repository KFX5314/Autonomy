-- ============================================================
-- TFG-DEMENCIA: MariaDB Schema
-- ============================================================
-- Run: mariadb -u root -p < init_db.sql
-- Or via Docker: docker exec -i mariadb mariadb -u root -prootpass < init_db.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS tfg_demencia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE tfg_demencia;

-- ============================================================
-- USERS: Both caregivers and patients authenticate here.
-- role = 'caregiver' | 'patient'
-- Caregivers authenticate with email. Patients authenticate with username
-- because they may not have an email account.
-- A patient row is linked to its caregiver via caregiver_id.
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    email           VARCHAR(255)    NULL UNIQUE COMMENT 'Required for caregivers; optional for patients',
    username        VARCHAR(64)     NULL UNIQUE COMMENT 'Required for patients; optional for caregivers',
    password_hash   VARCHAR(255)    NOT NULL,
    full_name       VARCHAR(255)    NOT NULL,
    role            ENUM('caregiver','patient') NOT NULL,
    caregiver_id    BIGINT          NULL COMMENT 'Only for role=patient: FK to their caregiver',
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_caregiver FOREIGN KEY (caregiver_id) REFERENCES users(id)
        ON DELETE SET NULL
);

-- ============================================================
-- PATIENTS: Extended profile for each patient user.
-- One-to-one with users WHERE role='patient'.
-- ============================================================
CREATE TABLE IF NOT EXISTS patients (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL UNIQUE,
    birth_date      DATE            NULL,
    notes           TEXT            NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_patient_user FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
);

-- ============================================================
-- PATIENT_CONTEXT: JSON-based flexible context per patient.
-- Maintained by the caregiver. Contains profile, triggers,
-- risk rules, assistant style, and rolling buffer config.
-- ============================================================
CREATE TABLE IF NOT EXISTS patient_context (
    patient_id      BIGINT          PRIMARY KEY,
    context_json    JSON            NOT NULL,
    updated_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_context_patient FOREIGN KEY (patient_id) REFERENCES patients(id)
        ON DELETE CASCADE
);

-- ============================================================
-- PUSH_TOKENS: Expo push tokens for caregiver devices.
-- ============================================================
CREATE TABLE IF NOT EXISTS push_tokens (
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
-- TRANSCRIPTS: Stored transcription results from audio chunks.
-- audio is NOT stored by default (privacy by design).
-- ============================================================
CREATE TABLE IF NOT EXISTS transcripts (
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
    INDEX idx_transcript_patient_time (patient_id, created_at)
);

-- ============================================================
-- ALERTS: Generated when an episode is detected.
-- Linked to the transcript that triggered it.
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    patient_id      BIGINT          NOT NULL,
    transcript_id   BIGINT          NULL,
    severity        TINYINT         NOT NULL CHECK (severity BETWEEN 1 AND 5),
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
    INDEX idx_alert_patient_status (patient_id, status)
);

-- ============================================================
-- CONVERSATION_HISTORY: Multi-turn assistant conversations
-- when the patient is in "assistant mode".
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_history (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    alert_id        BIGINT          NOT NULL,
    role            ENUM('patient','assistant') NOT NULL,
    message         TEXT            NOT NULL,
    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_convo_alert FOREIGN KEY (alert_id) REFERENCES alerts(id)
        ON DELETE CASCADE,
    INDEX idx_convo_alert (alert_id)
);
