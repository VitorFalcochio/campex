from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import DATABASE_PATH


_INIT_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[str] = set()


def _database_identity(connection: sqlite3.Connection) -> str:
    rows = connection.execute("PRAGMA database_list").fetchall()
    for row in rows:
        name = row["name"] if isinstance(row, sqlite3.Row) else row[1]
        if name != "main":
            continue
        filename = row["file"] if isinstance(row, sqlite3.Row) else row[2]
        if filename:
            return str(Path(filename).resolve())
    # Each in-memory connection owns a distinct database.
    return f":memory:{id(connection)}"


def connect(db_path: str | Path = DATABASE_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    database_id = _database_identity(connection)
    if database_id in _INITIALIZED_DATABASES:
        return

    with _INIT_LOCK:
        if database_id in _INITIALIZED_DATABASES:
            return
        if not database_id.startswith(":memory:"):
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
        _initialize_schema(connection)
        _INITIALIZED_DATABASES.add(database_id)


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            documento TEXT,
            status TEXT NOT NULL DEFAULT 'ativo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS unidades (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            localizacao TEXT,
            timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        );

        CREATE TABLE IF NOT EXISTS dispositivos (
            id TEXT PRIMARY KEY,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'offline',
            ultimo_contato TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (unidade_id) REFERENCES unidades (id)
        );

        CREATE TABLE IF NOT EXISTS cameras (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            unidade_id TEXT NOT NULL,
            dispositivo_id TEXT,
            edge_id TEXT,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'nao_conectada',
            config_ref TEXT,
            source_type TEXT,
            secure_ref TEXT,
            canal TEXT,
            ativa INTEGER NOT NULL DEFAULT 1,
            ultimo_frame TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id),
            FOREIGN KEY (dispositivo_id) REFERENCES dispositivos (id)
        );

        CREATE TABLE IF NOT EXISTS operational_areas (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'production_area',
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id)
        );

        CREATE TABLE IF NOT EXISTS operational_processes (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            area_id TEXT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'station',
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id),
            FOREIGN KEY (area_id) REFERENCES operational_areas (id)
        );

        CREATE TABLE IF NOT EXISTS operational_assets (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            area_id TEXT,
            process_id TEXT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'machine',
            ativo INTEGER NOT NULL DEFAULT 1,
            economic_method TEXT,
            downtime_cost_per_hour REAL,
            production_rate_per_hour REAL,
            contribution_value_per_unit REAL,
            economic_currency TEXT,
            economic_effective_from TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id),
            FOREIGN KEY (area_id) REFERENCES operational_areas (id),
            FOREIGN KEY (process_id) REFERENCES operational_processes (id)
        );

        CREATE TABLE IF NOT EXISTS regras (
            id TEXT PRIMARY KEY,
            camera_id TEXT NOT NULL,
            tipo_evento TEXT NOT NULL,
            tempo_minimo REAL NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            nome TEXT,
            cliente_id TEXT,
            unidade_id TEXT,
            entidade TEXT,
            regiao_id TEXT,
            condicao_json TEXT,
            severidade TEXT NOT NULL DEFAULT 'medium',
            cooldown_seconds REAL NOT NULL DEFAULT 60,
            destinatarios_json TEXT NOT NULL DEFAULT '[]',
            alerta_inicio INTEGER NOT NULL DEFAULT 1,
            alerta_normalizacao INTEGER NOT NULL DEFAULT 0,
            debounce_seconds REAL NOT NULL DEFAULT 1,
            hysteresis_seconds REAL NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS eventos (
            id TEXT PRIMARY KEY,
            event_uuid TEXT,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            inicio TEXT NOT NULL,
            fim TEXT,
            duracao REAL,
            operador_presente INTEGER,
            confianca REAL,
            midia_path TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (unidade_id) REFERENCES unidades (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS sync_outbox (
            id TEXT PRIMARY KEY,
            event_uuid TEXT NOT NULL UNIQUE,
            edge_id TEXT,
            tenant_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_attempt_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            synced_at TEXT
        );

        CREATE TABLE IF NOT EXISTS alertas (
            id TEXT PRIMARY KEY,
            evento_id TEXT NOT NULL,
            canal TEXT NOT NULL,
            destinatario TEXT,
            status TEXT NOT NULL DEFAULT 'pendente',
            horario TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (evento_id) REFERENCES eventos (id)
        );

        CREATE TABLE IF NOT EXISTS edge_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            uptime_seconds REAL NOT NULL,
            cpu_percent REAL,
            memory_percent REAL,
            active_cameras INTEGER NOT NULL DEFAULT 0,
            frames_processed INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS monitored_areas (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            unidade_id TEXT,
            camera_id TEXT NOT NULL,
            machine_id TEXT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'restricted_area',
            pontos_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            collaborator_name TEXT,
            expected_start TEXT,
            expected_end TEXT,
            absence_tolerance_seconds REAL,
            dwell_limit_seconds REAL,
            expected_min_people INTEGER,
            ativa INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS alert_recipients (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            event_types TEXT NOT NULL DEFAULT '[]',
            ativo INTEGER NOT NULL DEFAULT 1,
            camera_id TEXT,
            area_id TEXT,
            severidade_minima TEXT NOT NULL DEFAULT 'low',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id),
            FOREIGN KEY (area_id) REFERENCES monitored_areas (id)
        );

        CREATE TABLE IF NOT EXISTS alert_deliveries (
            id TEXT PRIMARY KEY,
            evento_id TEXT,
            decision_id TEXT,
            incident_key TEXT,
            alert_type TEXT,
            severity TEXT,
            recipient_id TEXT NOT NULL,
            destinatario TEXT,
            canal TEXT NOT NULL DEFAULT 'email',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT,
            next_attempt_at TEXT,
            sent_at TEXT,
            erro TEXT,
            is_test INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (evento_id, recipient_id, canal),
            FOREIGN KEY (evento_id) REFERENCES eventos (id),
            FOREIGN KEY (recipient_id) REFERENCES alert_recipients (id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            nome TEXT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        );

        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS technical_notices (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            camera_id TEXT,
            component TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            inicio TEXT NOT NULL,
            fim TEXT,
            erro TEXT,
            email_sent INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS installation_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS machine_monitors (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            machine_polygon_json TEXT NOT NULL,
            operator_polygon_json TEXT NOT NULL,
            operation_polygon_json TEXT,
            presence_scope TEXT NOT NULL DEFAULT 'OPERATOR_ZONE',
            ativo INTEGER NOT NULL DEFAULT 1,
            motion_sensitivity REAL NOT NULL DEFAULT 25.0,
            motion_threshold REAL,
            stop_seconds REAL NOT NULL DEFAULT 10.0,
            recovery_seconds REAL NOT NULL DEFAULT 3.0,
            replay_pre_seconds REAL NOT NULL DEFAULT 60.0,
            replay_post_seconds REAL NOT NULL DEFAULT 30.0,
            calibration_status TEXT NOT NULL DEFAULT 'not_calibrated',
            running_motion REAL,
            stopped_motion REAL,
            active_baseline REAL,
            stopped_baseline REAL,
            active_noise REAL,
            stopped_noise REAL,
            machine_state_official TEXT NOT NULL DEFAULT 'UNKNOWN',
            confidence REAL NOT NULL DEFAULT 0,
            state_reason TEXT,
            machine_state_since TEXT,
            operator_absence_seconds REAL NOT NULL DEFAULT 30.0,
            stopped_with_operator_seconds REAL NOT NULL DEFAULT 120.0,
            microstop_window_seconds REAL NOT NULL DEFAULT 3600.0,
            microstop_limit INTEGER NOT NULL DEFAULT 5,
            loss_model TEXT,
            loss_per_minute REAL,
            units_per_minute REAL,
            margin_per_unit REAL,
            indicator_polygon_json TEXT,
            indicator_on_baseline REAL,
            indicator_off_baseline REAL,
            active_calibration_json TEXT,
            stopped_calibration_json TEXT,
            separation_score REAL,
            calibration_result TEXT NOT NULL DEFAULT 'INVALID',
            calibration_algorithm_version TEXT,
            current_state TEXT NOT NULL DEFAULT 'unavailable',
            current_motion REAL,
            operator_present INTEGER NOT NULL DEFAULT 0,
            last_state_change TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clientes (id),
            FOREIGN KEY (unit_id) REFERENCES unidades (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS machine_calibrations (
            id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            samples_json TEXT NOT NULL,
            stats_json TEXT NOT NULL,
            baseline REAL,
            algorithm_version TEXT NOT NULL,
            region_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (machine_id) REFERENCES machine_monitors (id),
            FOREIGN KEY (camera_id) REFERENCES cameras (id)
        );

        CREATE TABLE IF NOT EXISTS operational_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            camera_id TEXT,
            machine_name TEXT,
            event_type TEXT NOT NULL,
            previous_state TEXT,
            new_state TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_seconds REAL,
            confidence REAL,
            activity_score REAL,
            people_count INTEGER NOT NULL DEFAULT 0,
            snapshot_path TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS operational_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_uuid TEXT UNIQUE,
            tenant_id TEXT,
            site_id TEXT,
            unit_id TEXT,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            camera_id TEXT,
            machine_id TEXT,
            machine_state TEXT,
            operator_present INTEGER,
            activity_score REAL,
            confidence REAL,
            capture_fps REAL,
            inference_fps REAL,
            frames_analyzed INTEGER NOT NULL DEFAULT 0,
            camera_online INTEGER,
            sample_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS machine_state_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            camera_id TEXT,
            state TEXT NOT NULL,
            activity_score REAL,
            confidence REAL,
            sample_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS operator_presence_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            camera_id TEXT,
            operator_present INTEGER NOT NULL,
            people_count INTEGER NOT NULL DEFAULT 0,
            confidence REAL,
            sample_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS evidences (
            id TEXT PRIMARY KEY,
            event_id TEXT,
            event_uuid TEXT,
            tenant_id TEXT,
            unit_id TEXT,
            camera_id TEXT,
            machine_id TEXT,
            path TEXT NOT NULL,
            media_type TEXT NOT NULL DEFAULT 'image',
            size_bytes INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE (event_id, path)
        );

        CREATE TABLE IF NOT EXISTS edge_heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            camera_online INTEGER NOT NULL DEFAULT 0,
            last_frame_at TEXT,
            capture_fps REAL,
            inference_fps REAL,
            frames_analyzed INTEGER NOT NULL DEFAULT 0,
            outbox_pending INTEGER NOT NULL DEFAULT 0,
            disk_free_bytes INTEGER,
            disk_used_percent REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS hourly_machine_metrics (
            id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            camera_id TEXT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            timezone TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            incomplete INTEGER NOT NULL DEFAULT 0,
            recalculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (machine_id, period_start, period_end)
        );

        CREATE TABLE IF NOT EXISTS daily_machine_metrics (
            id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            camera_id TEXT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            timezone TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            incomplete INTEGER NOT NULL DEFAULT 0,
            recalculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (machine_id, period_start, period_end)
        );

        CREATE TABLE IF NOT EXISTS shift_machine_metrics (
            id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            camera_id TEXT,
            shift_name TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            timezone TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            incomplete INTEGER NOT NULL DEFAULT 0,
            recalculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (machine_id, shift_name, period_start, period_end)
        );

        CREATE TABLE IF NOT EXISTS generated_insights (
            id TEXT PRIMARY KEY,
            machine_id TEXT,
            camera_id TEXT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            related_event_ids_json TEXT NOT NULL DEFAULT '[]',
            rule_id TEXT NOT NULL,
            recommended_action TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (machine_id, period_start, period_end, rule_id)
        );

        CREATE TABLE IF NOT EXISTS video_understandings (
            understanding_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            context_id TEXT NOT NULL,
            tenant_id TEXT,
            site_id TEXT,
            unit_id TEXT,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            camera_id TEXT,
            trigger_type TEXT,
            trigger_ref TEXT,
            provider TEXT,
            model TEXT,
            schema_version TEXT NOT NULL,
            prompt_version TEXT,
            status TEXT NOT NULL,
            quality TEXT NOT NULL,
            summary TEXT,
            structured_result_json TEXT NOT NULL DEFAULT '{}',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            uncertainties_json TEXT NOT NULL DEFAULT '[]',
            conflicts_json TEXT NOT NULL DEFAULT '[]',
            quality_reasons_json TEXT NOT NULL DEFAULT '[]',
            validation_errors_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS operational_alert_decisions (
            decision_id TEXT PRIMARY KEY,
            decision_key TEXT NOT NULL UNIQUE,
            incident_key TEXT NOT NULL,
            tenant_id TEXT,
            site_id TEXT,
            unit_id TEXT,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            camera_id TEXT,
            alert_type TEXT NOT NULL,
            decision TEXT NOT NULL,
            severity TEXT NOT NULL,
            priority TEXT,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            source_refs_json TEXT NOT NULL DEFAULT '[]',
            event_refs_json TEXT NOT NULL DEFAULT '[]',
            anomaly_refs_json TEXT NOT NULL DEFAULT '[]',
            understanding_refs_json TEXT NOT NULL DEFAULT '[]',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            reason_codes_json TEXT NOT NULL DEFAULT '[]',
            suppression_json TEXT,
            quality_json TEXT NOT NULL DEFAULT '{}',
            visual_summary TEXT,
            visual_facts_json TEXT NOT NULL DEFAULT '[]',
            uncertainties_json TEXT NOT NULL DEFAULT '[]',
            cause_inferred INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            actor_user_id TEXT,
            actor_email TEXT,
            actor_role TEXT,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            tenant_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS visual_rule_states (
            rule_id TEXT PRIMARY KEY,
            candidate_state INTEGER NOT NULL DEFAULT 0,
            candidate_since TEXT,
            active_event_id TEXT,
            active_since TEXT,
            last_closed_at TEXT,
            last_alert_at TEXT,
            last_evaluated_at TEXT,
            current_value_json TEXT NOT NULL DEFAULT '{}',
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rule_id) REFERENCES regras (id)
        );
        """
    )
    _ensure_column(connection, "clientes", "documento", "TEXT")
    _ensure_column(connection, "unidades", "timezone", "TEXT NOT NULL DEFAULT 'America/Sao_Paulo'")
    _ensure_column(connection, "cameras", "cliente_id", "TEXT")
    _ensure_column(connection, "cameras", "edge_id", "TEXT")
    _ensure_column(connection, "cameras", "source_type", "TEXT")
    _ensure_column(connection, "cameras", "secure_ref", "TEXT")
    _ensure_column(connection, "cameras", "ultimo_frame", "TEXT")
    _ensure_column(connection, "cameras", "ultimo_erro", "TEXT")
    _ensure_column(connection, "cameras", "reconexoes", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "frames_processados", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "rtsp_host", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_port", "INTEGER")
    _ensure_column(connection, "cameras", "rtsp_path", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_username", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_password", "TEXT")
    _ensure_column(connection, "cameras", "rtsp_password_encrypted", "TEXT")
    _ensure_column(connection, "cameras", "monitoring_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "analysis_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "cameras", "resolucao", "TEXT")
    _ensure_column(connection, "cameras", "fps", "REAL")
    _ensure_column(connection, "cameras", "canal", "TEXT")
    _ensure_column(connection, "cameras", "ativa", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "cameras", "site_id", "TEXT")
    _ensure_column(connection, "cameras", "area_context_id", "TEXT")
    _ensure_column(connection, "cameras", "process_id", "TEXT")
    _ensure_column(connection, "cameras", "asset_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "cliente_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "unidade_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "machine_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "site_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "area_context_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "process_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "asset_id", "TEXT")
    _ensure_column(connection, "monitored_areas", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "monitored_areas", "collaborator_name", "TEXT")
    _ensure_column(connection, "monitored_areas", "expected_start", "TEXT")
    _ensure_column(connection, "monitored_areas", "expected_end", "TEXT")
    _ensure_column(connection, "monitored_areas", "absence_tolerance_seconds", "REAL")
    _ensure_column(connection, "monitored_areas", "dwell_limit_seconds", "REAL")
    _ensure_column(connection, "monitored_areas", "expected_min_people", "INTEGER")
    _ensure_column(connection, "alert_recipients", "cliente_id", "TEXT")
    _ensure_column(connection, "alert_recipients", "event_types", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "alert_deliveries", "destinatario", "TEXT")
    _ensure_column(connection, "alert_deliveries", "decision_id", "TEXT")
    _ensure_column(connection, "alert_deliveries", "incident_key", "TEXT")
    _ensure_column(connection, "alert_deliveries", "alert_type", "TEXT")
    _ensure_column(connection, "alert_deliveries", "severity", "TEXT")
    _ensure_column(connection, "alert_deliveries", "payload_json", "TEXT NOT NULL DEFAULT '{}'")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_deliveries_decision_channel
        ON alert_deliveries (decision_id, recipient_id, canal)
        WHERE decision_id IS NOT NULL
        """
    )
    _ensure_column(connection, "users", "nome", "TEXT")
    _ensure_column(connection, "eventos", "area_id", "TEXT")
    _ensure_column(connection, "eventos", "regra_id", "TEXT")
    _ensure_column(connection, "eventos", "severidade", "TEXT NOT NULL DEFAULT 'high'")
    _ensure_column(connection, "eventos", "status", "TEXT NOT NULL DEFAULT 'closed'")
    _ensure_column(connection, "eventos", "quantidade_inicial", "INTEGER")
    _ensure_column(connection, "eventos", "quantidade_atual", "INTEGER")
    _ensure_column(connection, "eventos", "quantidade_maxima", "INTEGER")
    _ensure_column(connection, "eventos", "track_ids_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "eventos", "observacao", "TEXT")
    _ensure_column(connection, "eventos", "acknowledged_at", "TEXT")
    _ensure_column(connection, "eventos", "acknowledged_by", "TEXT")
    _ensure_column(connection, "eventos", "workflow_status", "TEXT NOT NULL DEFAULT 'new'")
    _ensure_column(connection, "eventos", "resolved_at", "TEXT")
    _ensure_column(connection, "eventos", "resolved_by", "TEXT")
    _ensure_column(connection, "eventos", "confirmed_cause", "TEXT")
    _ensure_column(connection, "eventos", "confirmed_by", "TEXT")
    _ensure_column(connection, "eventos", "confirmed_at", "TEXT")
    _ensure_column(connection, "eventos", "action_taken", "TEXT")
    _ensure_column(connection, "eventos", "action_at", "TEXT")
    _ensure_column(connection, "eventos", "recommendation_id", "TEXT")
    _ensure_column(connection, "eventos", "recommendation_accepted", "INTEGER")
    _ensure_column(connection, "eventos", "outcome_status", "TEXT")
    _ensure_column(connection, "eventos", "outcome_notes", "TEXT")
    _ensure_column(connection, "eventos", "resolution_time_seconds", "REAL")
    _ensure_column(connection, "eventos", "human_notes", "TEXT")
    _ensure_column(connection, "eventos", "event_family", "TEXT")
    _ensure_column(connection, "eventos", "event_subtype", "TEXT")
    _ensure_column(connection, "eventos", "ultimo_ocupado_em", "TEXT")
    _ensure_column(connection, "eventos", "evidence_error", "TEXT")
    _ensure_column(connection, "eventos", "atualizado_em", "TEXT")
    _ensure_column(connection, "eventos", "machine_monitor_id", "TEXT")
    _ensure_column(connection, "eventos", "motion_level", "REAL")
    _ensure_column(connection, "eventos", "operator_present_start", "INTEGER")
    _ensure_column(connection, "eventos", "operator_present_seconds", "REAL")
    _ensure_column(connection, "eventos", "operator_absent_seconds", "REAL")
    _ensure_column(connection, "eventos", "max_people", "INTEGER")
    _ensure_column(connection, "eventos", "replay_path", "TEXT")
    _ensure_column(connection, "eventos", "replay_error", "TEXT")
    _ensure_column(connection, "eventos", "cause_category", "TEXT")
    _ensure_column(connection, "eventos", "cause_notes", "TEXT")
    _ensure_column(connection, "eventos", "classified_at", "TEXT")
    _ensure_column(connection, "eventos", "classified_by", "TEXT")
    _ensure_column(connection, "eventos", "site_id", "TEXT")
    _ensure_column(connection, "eventos", "area_context_id", "TEXT")
    _ensure_column(connection, "eventos", "process_id", "TEXT")
    _ensure_column(connection, "eventos", "asset_id", "TEXT")
    _ensure_column(connection, "operational_assets", "economic_method", "TEXT")
    _ensure_column(connection, "operational_assets", "downtime_cost_per_hour", "REAL")
    _ensure_column(connection, "operational_assets", "production_rate_per_hour", "REAL")
    _ensure_column(connection, "operational_assets", "contribution_value_per_unit", "REAL")
    _ensure_column(connection, "operational_assets", "economic_currency", "TEXT")
    _ensure_column(connection, "operational_assets", "economic_effective_from", "TEXT")
    _ensure_column(connection, "operational_events", "activity_score", "REAL")
    _ensure_column(connection, "operational_events", "snapshot_path", "TEXT")
    _ensure_column(connection, "operational_events", "machine_id", "TEXT")
    _ensure_column(connection, "operational_events", "tenant_id", "TEXT")
    _ensure_column(connection, "operational_events", "unit_id", "TEXT")
    _ensure_column(connection, "operational_events", "status", "TEXT NOT NULL DEFAULT 'closed'")
    _ensure_column(connection, "operational_events", "severity", "TEXT")
    _ensure_column(connection, "operational_events", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "regras", "nome", "TEXT")
    _ensure_column(connection, "regras", "cliente_id", "TEXT")
    _ensure_column(connection, "regras", "unidade_id", "TEXT")
    _ensure_column(connection, "regras", "entidade", "TEXT")
    _ensure_column(connection, "regras", "regiao_id", "TEXT")
    _ensure_column(connection, "regras", "condicao_json", "TEXT")
    _ensure_column(connection, "regras", "severidade", "TEXT NOT NULL DEFAULT 'medium'")
    _ensure_column(connection, "regras", "cooldown_seconds", "REAL NOT NULL DEFAULT 60")
    _ensure_column(connection, "regras", "destinatarios_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "regras", "alerta_inicio", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "regras", "alerta_normalizacao", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "regras", "debounce_seconds", "REAL NOT NULL DEFAULT 1")
    _ensure_column(connection, "regras", "hysteresis_seconds", "REAL NOT NULL DEFAULT 1")
    _ensure_column(connection, "regras", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "regras", "atualizado_em", "TEXT")
    _ensure_column(connection, "eventos", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "eventos", "event_uuid", "TEXT")
    _ensure_column(connection, "machine_monitors", "site_id", "TEXT")
    _ensure_column(connection, "machine_monitors", "area_context_id", "TEXT")
    _ensure_column(connection, "machine_monitors", "process_id", "TEXT")
    _ensure_column(connection, "machine_monitors", "asset_id", "TEXT")
    _ensure_column(connection, "machine_monitors", "operation_polygon_json", "TEXT")
    _ensure_column(connection, "machine_monitors", "presence_scope", "TEXT NOT NULL DEFAULT 'OPERATOR_ZONE'")
    _ensure_column(connection, "machine_monitors", "active_baseline", "REAL")
    _ensure_column(connection, "machine_monitors", "stopped_baseline", "REAL")
    _ensure_column(connection, "machine_monitors", "active_noise", "REAL")
    _ensure_column(connection, "machine_monitors", "stopped_noise", "REAL")
    _ensure_column(connection, "machine_monitors", "machine_state_official", "TEXT NOT NULL DEFAULT 'UNKNOWN'")
    _ensure_column(connection, "machine_monitors", "confidence", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "machine_monitors", "state_reason", "TEXT")
    _ensure_column(connection, "machine_monitors", "machine_state_since", "TEXT")
    _ensure_column(connection, "machine_monitors", "operator_absence_seconds", "REAL NOT NULL DEFAULT 30.0")
    _ensure_column(connection, "machine_monitors", "stopped_with_operator_seconds", "REAL NOT NULL DEFAULT 120.0")
    _ensure_column(connection, "machine_monitors", "microstop_window_seconds", "REAL NOT NULL DEFAULT 3600.0")
    _ensure_column(connection, "machine_monitors", "microstop_limit", "INTEGER NOT NULL DEFAULT 5")
    _ensure_column(connection, "machine_monitors", "loss_model", "TEXT")
    _ensure_column(connection, "machine_monitors", "loss_per_minute", "REAL")
    _ensure_column(connection, "machine_monitors", "units_per_minute", "REAL")
    _ensure_column(connection, "machine_monitors", "margin_per_unit", "REAL")
    _ensure_column(connection, "machine_monitors", "indicator_polygon_json", "TEXT")
    _ensure_column(connection, "machine_monitors", "indicator_on_baseline", "REAL")
    _ensure_column(connection, "machine_monitors", "indicator_off_baseline", "REAL")
    _ensure_column(connection, "machine_monitors", "active_calibration_json", "TEXT")
    _ensure_column(connection, "machine_monitors", "stopped_calibration_json", "TEXT")
    _ensure_column(connection, "machine_monitors", "separation_score", "REAL")
    _ensure_column(connection, "machine_monitors", "calibration_result", "TEXT NOT NULL DEFAULT 'INVALID'")
    _ensure_column(connection, "machine_monitors", "calibration_algorithm_version", "TEXT")
    _ensure_column(connection, "operational_samples", "site_id", "TEXT")
    _ensure_column(connection, "operational_samples", "area_context_id", "TEXT")
    _ensure_column(connection, "operational_samples", "process_id", "TEXT")
    _ensure_column(connection, "operational_samples", "asset_id", "TEXT")
    _ensure_column(connection, "video_understandings", "site_id", "TEXT")
    _ensure_column(connection, "video_understandings", "unit_id", "TEXT")
    _ensure_column(connection, "video_understandings", "area_context_id", "TEXT")
    _ensure_column(connection, "video_understandings", "process_id", "TEXT")
    _ensure_column(connection, "video_understandings", "validation_errors_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "operational_alert_decisions", "unit_id", "TEXT")
    _ensure_column(connection, "operational_alert_decisions", "area_context_id", "TEXT")
    _ensure_column(connection, "operational_alert_decisions", "process_id", "TEXT")
    _backfill_operational_context(connection)
    _backfill_event_workflow(connection)
    _backfill_event_taxonomy(connection)
    cleanup_technical_camera_status_events(connection)
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_operational_context(connection: sqlite3.Connection) -> None:
    connection.execute("UPDATE cameras SET site_id = COALESCE(site_id, unidade_id)")
    connection.execute("UPDATE monitored_areas SET site_id = COALESCE(site_id, unidade_id)")
    connection.execute("UPDATE machine_monitors SET site_id = COALESCE(site_id, unit_id)")
    connection.execute("UPDATE eventos SET site_id = COALESCE(site_id, unidade_id)")
    connection.execute("UPDATE operational_samples SET site_id = COALESCE(site_id, unit_id)")


def _backfill_event_workflow(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET workflow_status = 'acknowledged',
            status = 'closed'
        WHERE status = 'acknowledged'
        """
    )
    connection.execute("UPDATE eventos SET workflow_status = COALESCE(workflow_status, 'new')")


def _backfill_event_taxonomy(connection: sqlite3.Connection) -> None:
    from app.event_taxonomy import EVENT_TAXONOMY

    connection.execute(
        """
        UPDATE eventos
        SET event_family = NULL,
            event_subtype = NULL
        WHERE tipo IN ('restricted_area_occupied', 'restricted_zone_occupied')
          AND event_family = 'flow'
        """
    )
    for event_type, taxonomy in EVENT_TAXONOMY.items():
        connection.execute(
            """
            UPDATE eventos
            SET event_family = COALESCE(event_family, ?),
                event_subtype = COALESCE(event_subtype, ?)
            WHERE tipo = ?
            """,
            (taxonomy.event_family, taxonomy.event_subtype, event_type),
        )


def cleanup_technical_camera_status_events(connection: sqlite3.Connection) -> int:
    """Remove legacy camera-status compatibility rows from the canonical event table.

    These rows were generated by the old operations-history compatibility layer.
    They represent technical telemetry, not operational events. The guard clauses
    intentionally keep any row that has evidence, human workflow/cause/action, or
    operational context.
    """
    rows = connection.execute(
        """
        SELECT id
        FROM eventos
        WHERE tipo = 'camera_status'
          AND json_extract(metadata_json, '$.domain') = 'operations_history_compat'
          AND COALESCE(midia_path, '') = ''
          AND COALESCE(acknowledged_at, '') = ''
          AND COALESCE(acknowledged_by, '') = ''
          AND COALESCE(resolved_at, '') = ''
          AND COALESCE(resolved_by, '') = ''
          AND COALESCE(confirmed_cause, '') = ''
          AND COALESCE(action_taken, '') = ''
          AND COALESCE(human_notes, '') = ''
          AND COALESCE(asset_id, '') = ''
          AND COALESCE(machine_monitor_id, '') = ''
          AND COALESCE(area_context_id, '') = ''
          AND COALESCE(process_id, '') = ''
        """
    ).fetchall()
    ids = [row["id"] for row in rows]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    connection.execute(f"DELETE FROM eventos WHERE id IN ({placeholders})", ids)
    return len(ids)
