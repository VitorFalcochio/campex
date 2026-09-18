from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.alerts import enqueue_event_alert
from app.config import EVIDENCE_DIR, storage_path
from app.database import init_db
from app.models import obter_camera, obter_regra, registrar_evento, atualizar_evento, atualizar_outbox_evento
from shared.schemas import now_iso


SUPPORTED_CONDITIONS = {
    "presence_in_zone",
    "absence_in_zone",
    "count_between",
    "class_count_between",
    "entry",
    "exit",
    "line_crossing",
    "movement_direction",
    "dwell_time",
    "proximity",
    "motion_in_region",
    "no_motion_in_region",
    "vehicle_stopped",
    "machine_state",
    "camera_quality",
    "camera_status",
    "all",
}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _seconds_between(start: str | None, end: str | None) -> float:
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    if not start_dt or not end_dt:
        return 0.0
    return max(0.0, (end_dt - start_dt).total_seconds())


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "sim", "yes", "online", "ativa", "presente"}
    return bool(value)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_condition(condition: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    kind = condition.get("type") or condition.get("kind")
    if kind not in SUPPORTED_CONDITIONS:
        return False, {"reason": "condition_not_supported", "condition": kind}

    if kind == "all":
        results = [evaluate_condition(item, facts) for item in condition.get("conditions", [])]
        return all(result[0] for result in results), {"children": [result[1] for result in results]}

    if kind == "presence_in_zone":
        zone_id = condition.get("zone_id") or condition.get("regiao_id")
        zone_counts = facts.get("zone_counts") or {}
        count = zone_counts.get(zone_id, facts.get("people_count", 0))
        return _number(count) >= _number(condition.get("min_count"), 1), {"count": count, "zone_id": zone_id}

    if kind == "absence_in_zone":
        zone_id = condition.get("zone_id") or condition.get("regiao_id")
        zone_counts = facts.get("zone_counts") or {}
        count = zone_counts.get(zone_id, facts.get("people_count", 0))
        return _number(count) <= _number(condition.get("max_count"), 0), {"count": count, "zone_id": zone_id}

    if kind == "count_between":
        value = _number(facts.get(condition.get("field", "people_count")))
        minimum = _number(condition.get("min"), float("-inf"))
        maximum = _number(condition.get("max"), float("inf"))
        return minimum <= value <= maximum, {"value": value, "min": minimum, "max": maximum}

    if kind == "class_count_between":
        class_name = condition.get("class_name", "person")
        class_counts = facts.get("class_counts") or {}
        value = _number(class_counts.get(class_name, 0))
        minimum = _number(condition.get("min"), float("-inf"))
        maximum = _number(condition.get("max"), float("inf"))
        return minimum <= value <= maximum, {"class_name": class_name, "value": value, "min": minimum, "max": maximum}

    if kind in {"entry", "exit", "line_crossing"}:
        events = set(facts.get("transitions") or facts.get("events") or [])
        expected = condition.get("event") or kind
        direction = condition.get("direction")
        ok = expected in events
        if direction:
            ok = ok and facts.get("direction") == direction
        return ok, {"event": expected, "direction": facts.get("direction")}

    if kind == "movement_direction":
        return facts.get("direction") == condition.get("direction"), {"direction": facts.get("direction")}

    if kind == "dwell_time":
        value = _number(facts.get("dwell_seconds"))
        return value >= _number(condition.get("seconds"), 0), {"dwell_seconds": value}

    if kind == "proximity":
        value = _number(facts.get("distance"))
        return value <= _number(condition.get("max_distance"), 0), {"distance": value}

    if kind == "motion_in_region":
        value = _number(facts.get("motion_score") or facts.get("activity_score"))
        return value >= _number(condition.get("min_motion"), 1), {"motion_score": value}

    if kind == "no_motion_in_region":
        value = _number(facts.get("motion_score") or facts.get("activity_score"))
        return value <= _number(condition.get("max_motion"), 0), {"motion_score": value}

    if kind == "vehicle_stopped":
        class_counts = facts.get("class_counts") or {}
        vehicles = sum(int(class_counts.get(name, 0) or 0) for name in ("car", "truck", "bus", "motorcycle", "vehicle"))
        motion = _number(facts.get("motion_score") or facts.get("activity_score"))
        return vehicles >= _number(condition.get("min_count"), 1) and motion <= _number(condition.get("max_motion"), 0), {
            "vehicles": vehicles,
            "motion_score": motion,
        }

    if kind == "machine_state":
        expected = condition.get("state")
        return facts.get("machine_state") == expected, {"machine_state": facts.get("machine_state")}

    if kind == "camera_quality":
        online_ok = True if condition.get("online") is None else facts.get("camera_status") == ("online" if condition.get("online") else "offline")
        fps_ok = _number(facts.get("fps")) >= _number(condition.get("min_fps"), 0)
        return online_ok and fps_ok, {"camera_status": facts.get("camera_status"), "fps": facts.get("fps")}

    if kind == "camera_status":
        return facts.get("camera_status") == condition.get("status"), {"camera_status": facts.get("camera_status")}

    return False, {"reason": "unreachable"}


def condition_templates() -> list[dict[str, Any]]:
    return [
        {"type": "all", "label": "Combinar condições"},
        {"type": "presence_in_zone", "label": "Presença em zona"},
        {"type": "absence_in_zone", "label": "Ausência em zona"},
        {"type": "count_between", "label": "Contagem mínima e máxima"},
        {"type": "class_count_between", "label": "Contagem por classe"},
        {"type": "entry", "label": "Entrada"},
        {"type": "exit", "label": "Saída"},
        {"type": "line_crossing", "label": "Cruzamento de linha"},
        {"type": "movement_direction", "label": "Direção de movimento"},
        {"type": "dwell_time", "label": "Permanência acima de limite"},
        {"type": "proximity", "label": "Proximidade"},
        {"type": "motion_in_region", "label": "Movimento em região"},
        {"type": "no_motion_in_region", "label": "Ausência de movimento em região"},
        {"type": "vehicle_stopped", "label": "Veículo parado"},
        {"type": "machine_state", "label": "Estado da máquina"},
        {"type": "camera_quality", "label": "Qualidade da câmera"},
        {"type": "camera_status", "label": "Disponibilidade da câmera"},
    ]


def default_rule_payloads(camera_id: str, zone_id: str | None = None) -> list[dict[str, Any]]:
    restricted_zone = zone_id or "restricted_area"
    return [
        {
            "nome": "Pessoa em área restrita",
            "camera_id": camera_id,
            "tipo_evento": "restricted_area_occupied",
            "entidade": "person",
            "regiao_id": restricted_zone,
            "tempo_minimo": 5,
            "severidade": "high",
            "cooldown_seconds": 60,
            "alerta_inicio": True,
            "alerta_normalizacao": True,
            "condicao": {"type": "presence_in_zone", "zone_id": restricted_zone, "min_count": 1},
        },
        {
            "nome": "Máquina ativa sem operador",
            "camera_id": camera_id,
            "tipo_evento": "active_without_operator",
            "entidade": "machine",
            "regiao_id": "operator",
            "tempo_minimo": 120,
            "severidade": "high",
            "cooldown_seconds": 300,
            "alerta_inicio": True,
            "alerta_normalizacao": True,
            "condicao": {
                "type": "all",
                "conditions": [
                    {"type": "machine_state", "state": "ATIVA"},
                    {"type": "absence_in_zone", "zone_id": "operator", "max_count": 0},
                ],
            },
        },
        {
            "nome": "Parada prolongada",
            "camera_id": camera_id,
            "tipo_evento": "machine_stoppage",
            "entidade": "machine",
            "tempo_minimo": 180,
            "severidade": "medium",
            "cooldown_seconds": 300,
            "alerta_inicio": True,
            "alerta_normalizacao": True,
            "condicao": {"type": "machine_state", "state": "PARADA"},
        },
        {
            "nome": "Muitas pessoas na zona",
            "camera_id": camera_id,
            "tipo_evento": "people_count_zone",
            "entidade": "person",
            "regiao_id": restricted_zone,
            "tempo_minimo": 5,
            "severidade": "medium",
            "cooldown_seconds": 120,
            "alerta_inicio": True,
            "alerta_normalizacao": True,
            "condicao": {"type": "presence_in_zone", "zone_id": restricted_zone, "min_count": 5},
        },
        {
            "nome": "Câmera offline",
            "camera_id": camera_id,
            "tipo_evento": "camera_offline",
            "entidade": "camera",
            "tempo_minimo": 60,
            "severidade": "critical",
            "cooldown_seconds": 300,
            "alerta_inicio": True,
            "alerta_normalizacao": True,
            "condicao": {"type": "camera_status", "status": "offline"},
        },
        {
            "nome": "Veículo parado",
            "camera_id": camera_id,
            "tipo_evento": "vehicle_stopped",
            "entidade": "vehicle",
            "tempo_minimo": 1200,
            "severidade": "medium",
            "cooldown_seconds": 600,
            "alerta_inicio": True,
            "alerta_normalizacao": True,
            "condicao": {"type": "vehicle_stopped", "min_count": 1, "max_motion": 1},
        },
    ]


def _state_row(connection, rule_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM visual_rule_states WHERE rule_id = ?", (rule_id,)).fetchone()
    if row:
        return dict(row)
    connection.execute(
        "INSERT INTO visual_rule_states (rule_id, last_evaluated_at) VALUES (?, ?)",
        (rule_id, now_iso()),
    )
    connection.commit()
    return dict(connection.execute("SELECT * FROM visual_rule_states WHERE rule_id = ?", (rule_id,)).fetchone())


def _camera_context(connection, rule: dict[str, Any]) -> tuple[str, str, str]:
    camera = obter_camera(connection, rule["camera_id"])
    if camera is None:
        return rule.get("cliente_id") or "", rule.get("unidade_id") or "", rule["camera_id"]
    return str(rule.get("cliente_id") or camera.get("cliente_id") or ""), str(rule.get("unidade_id") or camera.get("unidade_id") or ""), str(camera["id"])


def _save_snapshot(rule: dict[str, Any], frame: np.ndarray | None) -> str | None:
    if frame is None:
        return None
    try:
        now = datetime.now(timezone.utc).astimezone()
        folder = EVIDENCE_DIR / str(rule["camera_id"]) / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now:%H%M%S}_{rule['id']}_{int(time.time() * 1000)}.jpg"
        if cv2.imwrite(str(path), frame):
            return storage_path(path)
    except Exception:
        return None
    return None


def _open_event(connection, rule: dict[str, Any], facts: dict[str, Any], detail: dict[str, Any], frame: np.ndarray | None, now: str) -> str:
    cliente_id, unidade_id, camera_id = _camera_context(connection, rule)
    event_id = registrar_evento(
        connection,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        camera_id=camera_id,
        tipo=rule["tipo_evento"],
        inicio=now,
        operador_presente=facts.get("operator_present"),
        confianca=facts.get("confidence"),
        midia_path=_save_snapshot(rule, frame),
    )
    connection.execute(
        """
        UPDATE eventos
        SET regra_id = ?,
            area_id = ?,
            severidade = ?,
            status = 'open',
            quantidade_inicial = ?,
            quantidade_atual = ?,
            quantidade_maxima = ?,
            metadata_json = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            rule["id"],
            rule.get("regiao_id"),
            rule.get("severidade") or "medium",
            int(facts.get("people_count") or 0),
            int(facts.get("people_count") or 0),
            int(facts.get("people_count") or 0),
            json.dumps({"rule": rule.get("nome"), "facts": facts, "condition": detail}, ensure_ascii=False),
            event_id,
        ),
    )
    connection.commit()
    return event_id


def evaluate_rule(connection, rule_id: str, facts: dict[str, Any], frame: np.ndarray | None = None, at: str | None = None) -> dict[str, Any]:
    init_db(connection)
    rule = obter_regra(connection, rule_id)
    if rule is None:
        raise ValueError("Regra nao encontrada.")
    if not rule.get("ativo"):
        return {"rule_id": rule_id, "matched": False, "event_id": None, "status": "disabled"}
    now = at or now_iso()
    state = _state_row(connection, rule_id)
    matched, detail = evaluate_condition(rule.get("condicao") or {}, facts)
    min_seconds = max(_number(rule.get("tempo_minimo")), _number(rule.get("debounce_seconds")))
    hysteresis_seconds = _number(rule.get("hysteresis_seconds"))
    cooldown_seconds = _number(rule.get("cooldown_seconds"))
    active_event_id = state.get("active_event_id")
    last_closed_at = state.get("last_closed_at")
    in_cooldown = bool(last_closed_at and _seconds_between(last_closed_at, now) < cooldown_seconds)

    event_id = active_event_id
    action = "unchanged"
    pending_alert: tuple[str, str] | None = None
    if matched:
        candidate_since = state.get("candidate_since") if state.get("candidate_state") else now
        candidate_age = _seconds_between(candidate_since, now)
        should_open = not active_event_id and not in_cooldown and candidate_age >= min_seconds
        if should_open:
            event_id = _open_event(connection, rule, facts, detail, frame, now)
            action = "opened"
            if rule.get("alerta_inicio"):
                pending_alert = (event_id, "start")
            connection.execute(
                """
                UPDATE visual_rule_states
                SET candidate_state = 1,
                    candidate_since = ?,
                    active_event_id = ?,
                    active_since = ?,
                    last_alert_at = ?,
                    last_evaluated_at = ?,
                    current_value_json = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE rule_id = ?
                """,
                (candidate_since, event_id, now, now, now, json.dumps(detail), rule_id),
            )
        elif active_event_id:
            connection.execute(
                """
                UPDATE eventos
                SET quantidade_atual = ?,
                    quantidade_maxima = MAX(COALESCE(quantidade_maxima, 0), ?),
                    confianca = MAX(COALESCE(confianca, 0), COALESCE(?, 0)),
                    metadata_json = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    int(facts.get("people_count") or 0),
                    int(facts.get("people_count") or 0),
                    facts.get("confidence"),
                    json.dumps({"rule": rule.get("nome"), "facts": facts, "condition": detail}, ensure_ascii=False),
                    active_event_id,
                ),
            )
            connection.execute(
                """
                UPDATE visual_rule_states
                SET candidate_state = 1,
                    last_evaluated_at = ?,
                    current_value_json = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE rule_id = ?
                """,
                (now, json.dumps(detail), rule_id),
            )
        else:
            connection.execute(
                """
                UPDATE visual_rule_states
                SET candidate_state = 1,
                    candidate_since = ?,
                    last_evaluated_at = ?,
                    current_value_json = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE rule_id = ?
                """,
                (candidate_since, now, json.dumps(detail), rule_id),
            )
    else:
        if active_event_id and _seconds_between(state.get("last_evaluated_at"), now) >= hysteresis_seconds:
            duration = _seconds_between(state.get("active_since"), now)
            atualizar_evento(connection, active_event_id, fim=now, duracao=duration)
            connection.execute(
                """
                UPDATE eventos
                SET status = 'closed',
                    quantidade_atual = 0,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (active_event_id,),
            )
            atualizar_outbox_evento(connection, active_event_id)
            action = "closed"
            event_id = active_event_id
            if rule.get("alerta_normalizacao"):
                pending_alert = (active_event_id, "normalization")
            connection.execute(
                """
                UPDATE visual_rule_states
                SET candidate_state = 0,
                    candidate_since = NULL,
                    active_event_id = NULL,
                    active_since = NULL,
                    last_closed_at = ?,
                    last_evaluated_at = ?,
                    current_value_json = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE rule_id = ?
                """,
                (now, now, json.dumps(detail), rule_id),
            )
        else:
            connection.execute(
                """
                UPDATE visual_rule_states
                SET candidate_state = 0,
                    candidate_since = NULL,
                    last_evaluated_at = ?,
                    current_value_json = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE rule_id = ?
                """,
                (now, json.dumps(detail), rule_id),
            )
    connection.commit()
    if pending_alert:
        enqueue_event_alert(pending_alert[0], phase=pending_alert[1])
    return {
        "rule_id": rule_id,
        "matched": matched,
        "action": action,
        "event_id": event_id,
        "cooldown": in_cooldown,
        "detail": detail,
    }
