from __future__ import annotations

import sqlite3
import json
import os
import uuid
from typing import Any

from app.event_taxonomy import classify_event_type
from app.security import decrypt_secret, encrypt_secret
from edge_agent.camera_connector import safe_source_ref
from edge_agent.sync_outbox import enqueue_sync_event, new_event_uuid, refresh_sync_event
from shared.schemas import now_iso


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def registrar_audit_log(
    connection: sqlite3.Connection,
    *,
    action: str,
    actor: dict[str, Any] | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    audit_id = new_id("aud")
    connection.execute(
        """
        INSERT INTO audit_log (
            id, actor_user_id, actor_email, actor_role, action, entity_type,
            entity_id, tenant_id, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            actor.get("id") if actor else None,
            actor.get("email") if actor else None,
            actor.get("role") if actor else None,
            action,
            entity_type,
            entity_id,
            tenant_id or (actor.get("cliente_id") if actor else None),
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    connection.commit()
    return audit_id


def criar_cliente(connection: sqlite3.Connection, nome: str, status: str = "ativo", documento: str | None = None) -> str:
    item_id = new_id("cli")
    connection.execute(
        "INSERT INTO clientes (id, nome, documento, status) VALUES (?, ?, ?, ?)",
        (item_id, nome, documento, status),
    )
    connection.commit()
    return item_id


def criar_unidade(
    connection: sqlite3.Connection,
    cliente_id: str,
    nome: str,
    localizacao: str | None = None,
    timezone: str = "America/Sao_Paulo",
) -> str:
    item_id = new_id("uni")
    connection.execute(
        "INSERT INTO unidades (id, cliente_id, nome, localizacao, timezone) VALUES (?, ?, ?, ?, ?)",
        (item_id, cliente_id, nome, localizacao, timezone),
    )
    connection.commit()
    return item_id


def criar_dispositivo(connection: sqlite3.Connection, unidade_id: str, nome: str, status: str = "offline") -> str:
    item_id = new_id("edge")
    connection.execute(
        "INSERT INTO dispositivos (id, unidade_id, nome, status, ultimo_contato) VALUES (?, ?, ?, ?, ?)",
        (item_id, unidade_id, nome, status, now_iso()),
    )
    connection.commit()
    return item_id


def criar_camera(
    connection: sqlite3.Connection,
    unidade_id: str,
    nome: str,
    dispositivo_id: str | None = None,
    config_ref: str | None = None,
    status: str = "nao_conectada",
    cliente_id: str | None = None,
    edge_id: str | None = None,
    source_type: str | None = None,
    secure_ref: str | None = None,
    rtsp_host: str | None = None,
    rtsp_port: int | None = None,
    rtsp_path: str | None = None,
    rtsp_username: str | None = None,
    rtsp_password: str | None = None,
    canal: str | None = None,
    ativa: bool = True,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
) -> str:
    item_id = new_id("cam")
    encrypted_password = encrypt_secret(rtsp_password)
    connection.execute(
        """
        INSERT INTO cameras (
            id, cliente_id, unidade_id, dispositivo_id, edge_id, nome, status,
            config_ref, source_type, secure_ref, rtsp_host, rtsp_port, rtsp_path,
            rtsp_username, rtsp_password, rtsp_password_encrypted, canal, ativa
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            cliente_id,
            unidade_id,
            dispositivo_id,
            edge_id or dispositivo_id,
            nome,
            status,
            config_ref,
            source_type,
            secure_ref,
            rtsp_host,
            rtsp_port,
            rtsp_path,
            rtsp_username,
            None,
            encrypted_password,
            canal,
            1 if ativa else 0,
        ),
    )
    connection.execute(
        """
        UPDATE cameras
        SET site_id = COALESCE(site_id, unidade_id),
            area_context_id = ?,
            process_id = ?,
            asset_id = ?
        WHERE id = ?
        """,
        (area_context_id, process_id, asset_id, item_id),
    )
    connection.commit()
    return item_id


def camera_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data.pop("rtsp_username", None)
    data.pop("rtsp_password", None)
    data.pop("rtsp_password_encrypted", None)
    if data.get("config_ref") and str(data["config_ref"]).lower().startswith(("rtsp://", "rtsps://")):
        data["config_ref"] = safe_source_ref(str(data["config_ref"]))
    return data


def criar_regra(
    connection: sqlite3.Connection,
    camera_id: str,
    tipo_evento: str,
    tempo_minimo: float = 0,
    ativo: bool = True,
    nome: str | None = None,
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    entidade: str | None = None,
    regiao_id: str | None = None,
    condicao: dict[str, Any] | None = None,
    severidade: str = "medium",
    cooldown_seconds: float = 60,
    destinatarios: list[str] | None = None,
    alerta_inicio: bool = True,
    alerta_normalizacao: bool = False,
    debounce_seconds: float = 1,
    hysteresis_seconds: float = 1,
    metadata: dict[str, Any] | None = None,
) -> str:
    item_id = new_id("regra")
    connection.execute(
        """
        INSERT INTO regras (
            id, camera_id, tipo_evento, tempo_minimo, ativo, nome, cliente_id,
            unidade_id, entidade, regiao_id, condicao_json, severidade,
            cooldown_seconds, destinatarios_json, alerta_inicio,
            alerta_normalizacao, debounce_seconds, hysteresis_seconds,
            metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            camera_id,
            tipo_evento,
            tempo_minimo,
            1 if ativo else 0,
            nome or tipo_evento,
            cliente_id,
            unidade_id,
            entidade,
            regiao_id,
            json.dumps(condicao or {"type": tipo_evento}),
            severidade,
            cooldown_seconds,
            json.dumps(destinatarios or []),
            1 if alerta_inicio else 0,
            1 if alerta_normalizacao else 0,
            debounce_seconds,
            hysteresis_seconds,
            json.dumps(metadata or {}),
        ),
    )
    connection.commit()
    return item_id


def regra_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativo"] = bool(data.get("ativo"))
    data["alerta_inicio"] = bool(data.get("alerta_inicio", 1))
    data["alerta_normalizacao"] = bool(data.get("alerta_normalizacao", 0))
    data["condicao"] = json.loads(data.pop("condicao_json", None) or "{}")
    data["destinatarios"] = json.loads(data.pop("destinatarios_json", None) or "[]")
    data["metadata"] = json.loads(data.pop("metadata_json", None) or "{}")
    return data


def listar_regras(connection: sqlite3.Connection, cliente_id: str | None = None, camera_id: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if cliente_id:
        clauses.append("(cliente_id = ? OR cliente_id IS NULL)")
        values.append(cliente_id)
    if camera_id:
        clauses.append("camera_id = ?")
        values.append(camera_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(f"SELECT * FROM regras {where} ORDER BY criado_em DESC", values).fetchall()
    return [regra_public_dict(row) for row in rows]


def obter_regra(connection: sqlite3.Connection, regra_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM regras WHERE id = ?", (regra_id,)).fetchone()
    return regra_public_dict(row) if row else None


def atualizar_regra(connection: sqlite3.Connection, regra_id: str, **updates: Any) -> dict[str, Any] | None:
    current = obter_regra(connection, regra_id)
    if current is None:
        return None
    next_data = {**current, **{key: value for key, value in updates.items() if value is not None}}
    connection.execute(
        """
        UPDATE regras
        SET nome = ?,
            tipo_evento = ?,
            tempo_minimo = ?,
            ativo = ?,
            entidade = ?,
            regiao_id = ?,
            condicao_json = ?,
            severidade = ?,
            cooldown_seconds = ?,
            destinatarios_json = ?,
            alerta_inicio = ?,
            alerta_normalizacao = ?,
            debounce_seconds = ?,
            hysteresis_seconds = ?,
            metadata_json = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            next_data.get("nome"),
            next_data.get("tipo_evento"),
            next_data.get("tempo_minimo") or 0,
            1 if next_data.get("ativo") else 0,
            next_data.get("entidade"),
            next_data.get("regiao_id"),
            json.dumps(next_data.get("condicao") or {}),
            next_data.get("severidade") or "medium",
            next_data.get("cooldown_seconds") or 0,
            json.dumps(next_data.get("destinatarios") or []),
            1 if next_data.get("alerta_inicio") else 0,
            1 if next_data.get("alerta_normalizacao") else 0,
            next_data.get("debounce_seconds") or 0,
            next_data.get("hysteresis_seconds") or 0,
            json.dumps(next_data.get("metadata") or {}),
            regra_id,
        ),
    )
    connection.commit()
    return obter_regra(connection, regra_id)


def registrar_evento(
    connection: sqlite3.Connection,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    tipo: str,
    inicio: str | None = None,
    fim: str | None = None,
    duracao: float | None = None,
    operador_presente: bool | None = None,
    confianca: float | None = None,
    midia_path: str | None = None,
    event_uuid: str | None = None,
) -> str:
    item_id = new_id("evt")
    event_uuid = event_uuid or new_event_uuid()
    inicio = inicio or now_iso()
    taxonomy = classify_event_type(tipo)
    connection.execute(
        """
        INSERT INTO eventos (
            id, event_uuid, cliente_id, unidade_id, camera_id, tipo, inicio, fim, duracao,
            operador_presente, confianca, midia_path, event_family, event_subtype
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            event_uuid,
            cliente_id,
            unidade_id,
            camera_id,
            tipo,
            inicio,
            fim,
            duracao,
            None if operador_presente is None else int(operador_presente),
            confianca,
            midia_path,
            taxonomy.event_family,
            taxonomy.event_subtype,
        ),
    )
    connection.commit()
    from app.operational_context import apply_context_to_event

    apply_context_to_event(connection, item_id, camera_id=camera_id)
    atualizar_outbox_evento(connection, item_id)
    return item_id


def _enqueue_evento_cloud(
    connection: sqlite3.Connection,
    *,
    event_uuid: str,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    tipo: str,
    inicio: str,
    fim: str | None = None,
    duracao: float | None = None,
    operador_presente: bool | None = None,
    confianca: float | None = None,
    midia_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    taxonomy = classify_event_type(tipo)
    payload = {
        "event_uuid": event_uuid,
        "tenant_id": cliente_id,
        "cliente_id": cliente_id,
        "unidade_id": unidade_id,
        "camera_id": camera_id,
        "tipo": tipo,
        "event_family": taxonomy.event_family,
        "event_subtype": taxonomy.event_subtype,
        "inicio": inicio,
        "fim": fim,
        "duracao": duracao,
        "operador_presente": operador_presente,
        "confianca": confianca,
        "midia_path": midia_path,
    }
    if metadata:
        payload["metadata"] = metadata
    enqueue_sync_event(
        connection,
        event_uuid=event_uuid,
        tenant_id=cliente_id,
        edge_id=os.getenv("CAMPEX_EDGE_ID"),
        payload=payload,
    )


def atualizar_outbox_evento(connection: sqlite3.Connection, evento_id: str) -> None:
    row = connection.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    if row is None or not row["event_uuid"]:
        return
    metadata: dict[str, Any] = {}
    if "metadata_json" in row.keys() and row["metadata_json"]:
        try:
            metadata = json.loads(row["metadata_json"])
        except json.JSONDecodeError:
            metadata = {}
    payload = {
        "event_uuid": row["event_uuid"],
        "tenant_id": row["cliente_id"],
        "cliente_id": row["cliente_id"],
        "unidade_id": row["unidade_id"],
        "camera_id": row["camera_id"],
        "tipo": row["tipo"],
        "event_family": row["event_family"] if "event_family" in row.keys() else None,
        "event_subtype": row["event_subtype"] if "event_subtype" in row.keys() else None,
        "inicio": row["inicio"],
        "fim": row["fim"],
        "duracao": row["duracao"],
        "operador_presente": None if row["operador_presente"] is None else bool(row["operador_presente"]),
        "confianca": row["confianca"],
        "midia_path": row["midia_path"],
        "severidade": row["severidade"] if "severidade" in row.keys() else None,
        "status": row["status"] if "status" in row.keys() else None,
        "site_id": row["site_id"] if "site_id" in row.keys() else row["unidade_id"],
        "area_context_id": row["area_context_id"] if "area_context_id" in row.keys() else None,
        "process_id": row["process_id"] if "process_id" in row.keys() else None,
        "asset_id": row["asset_id"] if "asset_id" in row.keys() else row["machine_monitor_id"] if "machine_monitor_id" in row.keys() else None,
    }
    if metadata:
        payload["metadata"] = metadata
    refresh_sync_event(
        connection,
        event_uuid=row["event_uuid"],
        payload=payload,
        tenant_id=row["cliente_id"],
        edge_id=os.getenv("CAMPEX_EDGE_ID"),
    )


def evento_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    if "track_ids_json" in data:
        data["track_ids"] = json.loads(data.pop("track_ids_json") or "[]")
    if "metadata_json" in data:
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    return data


def criar_ocorrencia_area_restrita(
    connection: sqlite3.Connection,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    area_id: str,
    regra_id: str | None,
    inicio: str,
    quantidade_inicial: int,
    quantidade_maxima: int,
    track_ids: list[int],
    confianca: float | None,
    midia_path: str | None,
    severidade: str = "high",
    evidence_error: str | None = None,
) -> str:
    evento_id = new_id("evt")
    event_uuid = new_event_uuid()
    track_ids_json = json.dumps(sorted(set(track_ids)))
    taxonomy = classify_event_type("restricted_area_occupied")
    connection.execute(
        """
        INSERT INTO eventos (
            id, event_uuid, cliente_id, unidade_id, camera_id, area_id, regra_id, tipo,
            severidade, status, inicio, quantidade_inicial, quantidade_atual,
            quantidade_maxima, track_ids_json, confianca, midia_path,
            ultimo_ocupado_em, evidence_error, event_family, event_subtype
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento_id,
            event_uuid,
            cliente_id,
            unidade_id,
            camera_id,
            area_id,
            regra_id,
            "restricted_area_occupied",
            severidade,
            "open",
            inicio,
            quantidade_inicial,
            quantidade_inicial,
            quantidade_maxima,
            track_ids_json,
            confianca,
            midia_path,
            inicio,
            evidence_error,
            taxonomy.event_family,
            taxonomy.event_subtype,
        ),
    )
    from app.operational_context import apply_context_to_event

    apply_context_to_event(connection, evento_id, camera_id=camera_id, area_id=area_id)
    _enqueue_evento_cloud(
        connection,
        event_uuid=event_uuid,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        camera_id=camera_id,
        tipo="restricted_area_occupied",
        inicio=inicio,
        operador_presente=True,
        confianca=confianca,
        midia_path=midia_path,
        metadata={"area_id": area_id, "regra_id": regra_id, "track_ids": sorted(set(track_ids))},
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()
    return evento_id


def criar_ocorrencia_zona(
    connection: sqlite3.Connection,
    *,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    area_id: str,
    regra_id: str | None,
    tipo: str,
    inicio: str,
    quantidade_inicial: int,
    quantidade_maxima: int,
    track_ids: list[int],
    confianca: float | None,
    midia_path: str | None,
    severidade: str = "medium",
    metadata: dict[str, Any] | None = None,
    evidence_error: str | None = None,
) -> str:
    evento_id = new_id("evt")
    event_uuid = new_event_uuid()
    track_ids_json = json.dumps(sorted(set(track_ids)))
    metadata = {**(metadata or {}), "area_id": area_id, "regra_id": regra_id, "track_ids": sorted(set(track_ids))}
    taxonomy = classify_event_type(tipo)
    connection.execute(
        """
        INSERT INTO eventos (
            id, event_uuid, cliente_id, unidade_id, camera_id, area_id, regra_id, tipo,
            severidade, status, inicio, quantidade_inicial, quantidade_atual,
            quantidade_maxima, track_ids_json, confianca, midia_path,
            ultimo_ocupado_em, metadata_json, evidence_error, event_family, event_subtype
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento_id,
            event_uuid,
            cliente_id,
            unidade_id,
            camera_id,
            area_id,
            regra_id,
            tipo,
            severidade,
            "open",
            inicio,
            quantidade_inicial,
            quantidade_inicial,
            quantidade_maxima,
            track_ids_json,
            confianca,
            midia_path,
            inicio,
            json.dumps(metadata),
            evidence_error,
            taxonomy.event_family,
            taxonomy.event_subtype,
        ),
    )
    from app.operational_context import apply_context_to_event

    apply_context_to_event(connection, evento_id, camera_id=camera_id, area_id=area_id)
    _enqueue_evento_cloud(
        connection,
        event_uuid=event_uuid,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        camera_id=camera_id,
        tipo=tipo,
        inicio=inicio,
        operador_presente=quantidade_inicial > 0,
        confianca=confianca,
        midia_path=midia_path,
        metadata=metadata,
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()
    return evento_id


def atualizar_ocorrencia_area(
    connection: sqlite3.Connection,
    evento_id: str,
    quantidade_atual: int,
    quantidade_maxima: int,
    track_ids: list[int],
    confianca: float | None,
    ultimo_ocupado_em: str,
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET quantidade_atual = ?,
            quantidade_maxima = MAX(COALESCE(quantidade_maxima, 0), ?),
            track_ids_json = ?,
            confianca = MAX(COALESCE(confianca, 0), COALESCE(?, 0)),
            ultimo_ocupado_em = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            quantidade_atual,
            quantidade_maxima,
            json.dumps(sorted(set(track_ids))),
            confianca,
            ultimo_ocupado_em,
            evento_id,
        ),
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()


def fechar_ocorrencia_area(
    connection: sqlite3.Connection,
    evento_id: str,
    fim: str,
    duracao: float,
    observacao: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET status = 'closed',
            fim = ?,
            duracao = ?,
            quantidade_atual = 0,
            observacao = COALESCE(?, observacao),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'open'
        """,
        (fim, duracao, observacao, evento_id),
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()


def reconhecer_ocorrencia(
    connection: sqlite3.Connection,
    evento_id: str,
    observacao: str | None,
    acknowledged_by: str | None,
    acknowledged_at: str,
) -> dict[str, Any] | None:
    from app.event_workflow import acknowledge_event

    return acknowledge_event(
        connection,
        evento_id,
        actor=acknowledged_by,
        human_notes=observacao,
        at=acknowledged_at,
    )


def obter_evento(connection: sqlite3.Connection, evento_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    return evento_public_dict(row) if row else None


def listar_eventos_filtrados(
    connection: sqlite3.Connection,
    camera_id: str | None = None,
    area_id: str | None = None,
    status: str | None = None,
    tipo: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    site_id: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    event_family: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    filters = {
        "camera_id": camera_id,
        "area_id": area_id,
        "status": status,
        "tipo": tipo,
        "site_id": site_id,
        "area_context_id": area_context_id,
        "process_id": process_id,
        "asset_id": asset_id,
        "event_family": event_family,
    }
    for column, value in filters.items():
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    if data_inicio:
        clauses.append("inicio >= ?")
        values.append(data_inicio)
    if data_fim:
        clauses.append("inicio <= ?")
        values.append(data_fim)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT * FROM eventos {where} ORDER BY inicio DESC, criado_em DESC LIMIT 200",
        values,
    ).fetchall()
    return [evento_public_dict(row) for row in rows]


def atualizar_evento(
    connection: sqlite3.Connection,
    evento_id: str,
    fim: str | None = None,
    duracao: float | None = None,
    operador_presente: bool | None = None,
    confianca: float | None = None,
    midia_path: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET
            fim = COALESCE(?, fim),
            duracao = COALESCE(?, duracao),
            operador_presente = COALESCE(?, operador_presente),
            confianca = COALESCE(?, confianca),
            midia_path = COALESCE(?, midia_path)
        WHERE id = ?
        """,
        (
            fim,
            duracao,
            None if operador_presente is None else int(operador_presente),
            confianca,
            midia_path,
            evento_id,
        ),
    )
    connection.commit()


def registrar_alerta(
    connection: sqlite3.Connection,
    evento_id: str,
    canal: str,
    destinatario: str | None = None,
    status: str = "pendente",
) -> str:
    item_id = new_id("alerta")
    connection.execute(
        "INSERT INTO alertas (id, evento_id, canal, destinatario, status) VALUES (?, ?, ?, ?, ?)",
        (item_id, evento_id, canal, destinatario, status),
    )
    connection.commit()
    return item_id


def atualizar_camera_status(
    connection: sqlite3.Connection,
    camera_id: str,
    status: str,
    ultimo_frame: str | None = None,
) -> None:
    connection.execute(
        "UPDATE cameras SET status = ?, ultimo_frame = COALESCE(?, ultimo_frame) WHERE id = ?",
        (status, ultimo_frame, camera_id),
    )
    connection.commit()


def atualizar_camera_operacao(
    connection: sqlite3.Connection,
    camera_id: str,
    status: str,
    ultimo_frame: str | None = None,
    ultimo_erro: str | None = None,
    reconectar: bool = False,
    frames_increment: int = 0,
) -> None:
    connection.execute(
        """
        UPDATE cameras
        SET
            status = ?,
            ultimo_frame = COALESCE(?, ultimo_frame),
            ultimo_erro = ?,
            reconexoes = reconexoes + ?,
            frames_processados = frames_processados + ?
        WHERE id = ?
        """,
        (
            status,
            ultimo_frame,
            ultimo_erro,
            1 if reconectar else 0,
            frames_increment,
            camera_id,
        ),
    )
    connection.commit()


def atualizar_camera_video_info(
    connection: sqlite3.Connection,
    camera_id: str,
    resolucao: str | None = None,
    fps: float | None = None,
) -> None:
    connection.execute(
        "UPDATE cameras SET resolucao = COALESCE(?, resolucao), fps = COALESCE(?, fps) WHERE id = ?",
        (resolucao, fps, camera_id),
    )
    connection.commit()


def listar_cameras_do_edge(connection: sqlite3.Connection, edge_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM cameras
        WHERE (edge_id = ? OR dispositivo_id = ?)
          AND status != 'inativa'
        ORDER BY nome
        """,
        (edge_id, edge_id),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def registrar_edge_metricas(
    connection: sqlite3.Connection,
    edge_id: str,
    uptime_seconds: float,
    cpu_percent: float | None,
    memory_percent: float | None,
    active_cameras: int,
    frames_processed: int,
) -> None:
    connection.execute(
        """
        INSERT INTO edge_metrics (
            edge_id, uptime_seconds, cpu_percent, memory_percent,
            active_cameras, frames_processed
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            edge_id,
            uptime_seconds,
            cpu_percent,
            memory_percent,
            active_cameras,
            frames_processed,
        ),
    )
    connection.commit()


def registrar_edge_heartbeat(
    connection: sqlite3.Connection,
    edge_id: str,
    *,
    heartbeat_at: str,
    camera_online: bool,
    last_frame_at: str | None,
    capture_fps: float | None,
    inference_fps: float | None,
    frames_analyzed: int,
    outbox_pending: int,
    disk_free_bytes: int | None,
    disk_used_percent: float | None,
) -> None:
    connection.execute(
        """
        INSERT INTO edge_heartbeats (
            edge_id, heartbeat_at, camera_online, last_frame_at, capture_fps,
            inference_fps, frames_analyzed, outbox_pending, disk_free_bytes,
            disk_used_percent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge_id,
            heartbeat_at,
            1 if camera_online else 0,
            last_frame_at,
            capture_fps,
            inference_fps,
            frames_analyzed,
            outbox_pending,
            disk_free_bytes,
            disk_used_percent,
        ),
    )
    connection.commit()


def ultimo_edge_heartbeat(connection: sqlite3.Connection, edge_id: str | None = None) -> dict[str, Any] | None:
    if edge_id:
        row = connection.execute(
            """
            SELECT *
            FROM edge_heartbeats
            WHERE edge_id = ?
            ORDER BY heartbeat_at DESC, id DESC
            LIMIT 1
            """,
            (edge_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT *
            FROM edge_heartbeats
            ORDER BY heartbeat_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return row_to_dict(row) if row else None


def registrar_operational_sample(
    connection: sqlite3.Connection,
    *,
    sample_uuid: str,
    tenant_id: str | None,
    unit_id: str | None,
    camera_id: str | None,
    machine_id: str | None,
    machine_state: str | None,
    operator_present: bool | None,
    activity_score: float | None,
    confidence: float | None,
    capture_fps: float | None,
    inference_fps: float | None,
    frames_analyzed: int,
    camera_online: bool | None,
    sample_at: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    from app.operational_context import resolve_context

    context = resolve_context(
        connection,
        camera_id=camera_id,
        machine_monitor_id=machine_id,
        fallback_cliente_id=tenant_id,
        fallback_unidade_id=unit_id,
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO operational_samples (
            sample_uuid, tenant_id, site_id, unit_id, area_context_id, process_id,
            asset_id, camera_id, machine_id, machine_state,
            operator_present, activity_score, confidence, capture_fps, inference_fps,
            frames_analyzed, camera_online, sample_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample_uuid,
            context.get("cliente_id") or tenant_id,
            context.get("site_id") or unit_id,
            context.get("unidade_id") or unit_id,
            context.get("area_context_id"),
            context.get("process_id"),
            context.get("asset_id") or machine_id,
            camera_id,
            machine_id,
            machine_state,
            None if operator_present is None else int(operator_present),
            activity_score,
            confidence,
            capture_fps,
            inference_fps,
            frames_analyzed,
            None if camera_online is None else int(camera_online),
            sample_at,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    if machine_id and machine_state:
        connection.execute(
            """
            INSERT INTO machine_state_samples (
                machine_id, camera_id, state, activity_score, confidence, sample_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (machine_id, camera_id, machine_state, activity_score, confidence, sample_at),
        )
    if operator_present is not None:
        connection.execute(
            """
            INSERT INTO operator_presence_samples (
                machine_id, camera_id, operator_present, people_count, confidence, sample_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (machine_id, camera_id, int(operator_present), int((metadata or {}).get("people_count") or 0), confidence, sample_at),
        )
    connection.commit()


def registrar_evidence_index(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    event_id: str | None,
    event_uuid: str | None,
    tenant_id: str | None,
    unit_id: str | None,
    camera_id: str | None,
    machine_id: str | None,
    path: str,
    media_type: str = "image",
    size_bytes: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO evidences (
            id, event_id, event_uuid, tenant_id, unit_id, camera_id, machine_id,
            path, media_type, size_bytes, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            event_id,
            event_uuid,
            tenant_id,
            unit_id,
            camera_id,
            machine_id,
            path,
            media_type,
            size_bytes,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    connection.commit()


def ultima_metrica_edge(connection: sqlite3.Connection, edge_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM edge_metrics
        WHERE edge_id = ?
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        """,
        (edge_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def listar(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    allowed = {"clientes", "unidades", "dispositivos", "cameras", "regras", "eventos", "alertas"}
    if table not in allowed:
        raise ValueError(f"Tabela inválida: {table}")
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY criado_em DESC")
    if table == "cameras":
        return [camera_public_dict(row) for row in rows]
    if table == "eventos":
        return [evento_public_dict(row) for row in rows]
    if table == "regras":
        return [regra_public_dict(row) for row in rows]
    return [row_to_dict(row) for row in rows]


def obter_camera(connection: sqlite3.Connection, camera_id: str, include_secret: bool = False) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        return None
    if not include_secret:
        return camera_public_dict(row)
    data = row_to_dict(row)
    if data.get("rtsp_password_encrypted"):
        data["rtsp_password"] = decrypt_secret(data["rtsp_password_encrypted"])
    return data


def area_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativa"] = bool(data["ativa"])
    data["pontos"] = json.loads(data.pop("pontos_json"))
    if "metadata_json" in data:
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    return data


def listar_areas_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM monitored_areas WHERE camera_id = ? ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [area_public_dict(row) for row in rows]


def listar_areas_ativas_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM monitored_areas WHERE camera_id = ? AND ativa = 1 ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [area_public_dict(row) for row in rows]


def criar_area_monitorada(
    connection: sqlite3.Connection,
    camera_id: str,
    nome: str,
    pontos: list[dict[str, float]],
    tipo: str = "restricted_area",
    ativa: bool = True,
    metadata: dict[str, Any] | None = None,
    collaborator_name: str | None = None,
    expected_start: str | None = None,
    expected_end: str | None = None,
    absence_tolerance_seconds: float | None = None,
    dwell_limit_seconds: float | None = None,
    expected_min_people: int | None = None,
    machine_id: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
) -> str:
    area_id = new_id("area")
    camera = connection.execute(
        """
        SELECT c.unidade_id, COALESCE(c.cliente_id, u.cliente_id) AS cliente_id
        FROM cameras c
        LEFT JOIN unidades u ON u.id = c.unidade_id
        WHERE c.id = ?
        """,
        (camera_id,),
    ).fetchone()
    cliente_id = camera["cliente_id"] if camera else None
    unidade_id = camera["unidade_id"] if camera else None
    connection.execute(
        """
        INSERT INTO monitored_areas (
            id, cliente_id, unidade_id, camera_id, machine_id, nome, tipo, pontos_json, metadata_json,
            collaborator_name, expected_start, expected_end,
            absence_tolerance_seconds, dwell_limit_seconds,
            expected_min_people, ativa
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            area_id,
            cliente_id,
            unidade_id,
            camera_id,
            machine_id,
            nome,
            tipo,
            json.dumps(pontos),
            json.dumps(metadata or {}),
            collaborator_name,
            expected_start,
            expected_end,
            absence_tolerance_seconds,
            dwell_limit_seconds,
            expected_min_people,
            1 if ativa else 0,
        ),
    )
    from app.operational_context import resolve_context

    context = resolve_context(connection, camera_id=camera_id, machine_monitor_id=machine_id)
    connection.execute(
        """
        UPDATE monitored_areas
        SET site_id = ?,
            area_context_id = COALESCE(?, ?),
            process_id = COALESCE(?, ?),
            asset_id = COALESCE(?, ?, machine_id)
        WHERE id = ?
        """,
        (
            context.get("site_id"),
            area_context_id,
            context.get("area_context_id"),
            process_id,
            context.get("process_id"),
            asset_id,
            context.get("asset_id"),
            area_id,
        ),
    )
    connection.commit()
    return area_id


def atualizar_area_monitorada(
    connection: sqlite3.Connection,
    area_id: str,
    nome: str | None = None,
    pontos: list[dict[str, float]] | None = None,
    tipo: str | None = None,
    ativa: bool | None = None,
    metadata: dict[str, Any] | None = None,
    collaborator_name: str | None = None,
    expected_start: str | None = None,
    expected_end: str | None = None,
    absence_tolerance_seconds: float | None = None,
    dwell_limit_seconds: float | None = None,
    expected_min_people: int | None = None,
    machine_id: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any] | None:
    existing = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area_id,)).fetchone()
    if existing is None:
        return None
    current = area_public_dict(existing)
    next_nome = nome if nome is not None else current["nome"]
    next_pontos = pontos if pontos is not None else current["pontos"]
    next_tipo = tipo if tipo is not None else current["tipo"]
    next_ativa = ativa if ativa is not None else current["ativa"]
    next_metadata = metadata if metadata is not None else current.get("metadata", {})
    connection.execute(
        """
        UPDATE monitored_areas
        SET nome = ?,
            tipo = ?,
            pontos_json = ?,
            metadata_json = ?,
            collaborator_name = COALESCE(?, collaborator_name),
            expected_start = COALESCE(?, expected_start),
            expected_end = COALESCE(?, expected_end),
            absence_tolerance_seconds = COALESCE(?, absence_tolerance_seconds),
            dwell_limit_seconds = COALESCE(?, dwell_limit_seconds),
            expected_min_people = COALESCE(?, expected_min_people),
            machine_id = COALESCE(?, machine_id),
            area_context_id = COALESCE(?, area_context_id),
            process_id = COALESCE(?, process_id),
            asset_id = COALESCE(?, asset_id),
            ativa = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            next_nome,
            next_tipo,
            json.dumps(next_pontos),
            json.dumps(next_metadata),
            collaborator_name,
            expected_start,
            expected_end,
            absence_tolerance_seconds,
            dwell_limit_seconds,
            expected_min_people,
            machine_id,
            area_context_id,
            process_id,
            asset_id,
            1 if next_ativa else 0,
            area_id,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area_id,)).fetchone()
    return area_public_dict(row) if row else None


def excluir_area_monitorada(connection: sqlite3.Connection, area_id: str) -> bool:
    cursor = connection.execute("DELETE FROM monitored_areas WHERE id = ?", (area_id,))
    connection.commit()
    return cursor.rowcount > 0


def alert_recipient_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativo"] = bool(data["ativo"])
    data["event_types"] = json.loads(data.get("event_types") or "[]")
    return data


def alert_delivery_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["is_test"] = bool(data["is_test"])
    if "payload_json" in data:
        data["payload"] = json.loads(data.pop("payload_json") or "{}")
    return data


def listar_alert_recipients(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM alert_recipients ORDER BY criado_em DESC").fetchall()
    return [alert_recipient_public_dict(row) for row in rows]


def criar_alert_recipient(
    connection: sqlite3.Connection,
    nome: str,
    email: str,
    ativo: bool = True,
    camera_id: str | None = None,
    area_id: str | None = None,
    severidade_minima: str = "low",
    cliente_id: str | None = None,
    event_types: list[str] | None = None,
) -> str:
    recipient_id = new_id("rec")
    connection.execute(
        """
        INSERT INTO alert_recipients (
            id, cliente_id, nome, email, event_types, ativo, camera_id, area_id, severidade_minima
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (recipient_id, cliente_id, nome, email, json.dumps(event_types or []), 1 if ativo else 0, camera_id, area_id, severidade_minima),
    )
    connection.commit()
    return recipient_id


def atualizar_alert_recipient(
    connection: sqlite3.Connection,
    recipient_id: str,
    nome: str | None = None,
    email: str | None = None,
    ativo: bool | None = None,
    camera_id: str | None = None,
    area_id: str | None = None,
    severidade_minima: str | None = None,
    event_types: list[str] | None = None,
) -> dict[str, Any] | None:
    existing = connection.execute("SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)).fetchone()
    if existing is None:
        return None
    current = alert_recipient_public_dict(existing)
    connection.execute(
        """
        UPDATE alert_recipients
        SET nome = ?,
            email = ?,
            ativo = ?,
            camera_id = ?,
            area_id = ?,
            severidade_minima = ?,
            event_types = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            nome if nome is not None else current["nome"],
            email if email is not None else current["email"],
            1 if (ativo if ativo is not None else current["ativo"]) else 0,
            camera_id if camera_id is not None else current.get("camera_id"),
            area_id if area_id is not None else current.get("area_id"),
            severidade_minima if severidade_minima is not None else current["severidade_minima"],
            json.dumps(event_types if event_types is not None else current.get("event_types", [])),
            recipient_id,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)).fetchone()
    return alert_recipient_public_dict(row) if row else None


def excluir_alert_recipient(connection: sqlite3.Connection, recipient_id: str) -> bool:
    cursor = connection.execute("DELETE FROM alert_recipients WHERE id = ?", (recipient_id,))
    connection.commit()
    return cursor.rowcount > 0


def listar_recipients_para_evento(connection: sqlite3.Connection, event: dict[str, Any]) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM alert_recipients
        WHERE ativo = 1
          AND (cliente_id IS NULL OR cliente_id = ?)
          AND (camera_id IS NULL OR camera_id = ?)
          AND (area_id IS NULL OR area_id = ?)
        ORDER BY criado_em DESC
        """,
        (event.get("cliente_id"), event.get("camera_id"), event.get("area_id")),
    ).fetchall()
    return [alert_recipient_public_dict(row) for row in rows]


def obter_alert_recipient(connection: sqlite3.Connection, recipient_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)).fetchone()
    return alert_recipient_public_dict(row) if row else None


def criar_alert_delivery(
    connection: sqlite3.Connection,
    recipient_id: str,
    evento_id: str | None = None,
    canal: str = "email",
    status: str = "pending",
    is_test: bool = False,
    decision_id: str | None = None,
    incident_key: str | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    delivery_id = new_id("del")
    if evento_id is not None:
        existing = connection.execute(
            "SELECT id FROM alert_deliveries WHERE evento_id = ? AND recipient_id = ? AND canal = ?",
            (evento_id, recipient_id, canal),
        ).fetchone()
        if existing:
            return str(existing["id"])
    if decision_id is not None:
        existing = connection.execute(
            "SELECT id FROM alert_deliveries WHERE decision_id = ? AND recipient_id = ? AND canal = ?",
            (decision_id, recipient_id, canal),
        ).fetchone()
        if existing:
            return str(existing["id"])
    connection.execute(
        """
        INSERT INTO alert_deliveries (
            id, evento_id, decision_id, incident_key, alert_type, severity,
            recipient_id, destinatario, canal, status, is_test, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, (SELECT email FROM alert_recipients WHERE id = ?), ?, ?, ?, ?)
        """,
        (
            delivery_id,
            evento_id,
            decision_id,
            incident_key,
            alert_type,
            severity,
            recipient_id,
            recipient_id,
            canal,
            status,
            1 if is_test else 0,
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )
    connection.commit()
    return delivery_id


def obter_alert_delivery(connection: sqlite3.Connection, delivery_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM alert_deliveries WHERE id = ?", (delivery_id,)).fetchone()
    return alert_delivery_public_dict(row) if row else None


def listar_alert_deliveries(
    connection: sqlite3.Connection,
    evento_id: str | None = None,
    recipient_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for column, value in {"evento_id": evento_id, "recipient_id": recipient_id, "status": status}.items():
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT * FROM alert_deliveries {where} ORDER BY criado_em DESC LIMIT 300",
        values,
    ).fetchall()
    return [alert_delivery_public_dict(row) for row in rows]


def atualizar_alert_delivery_attempt(
    connection: sqlite3.Connection,
    delivery_id: str,
    status: str,
    attempts: int,
    last_attempt_at: str,
    next_attempt_at: str | None = None,
    sent_at: str | None = None,
    erro: str | None = None,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE alert_deliveries
        SET status = ?,
            attempts = ?,
            last_attempt_at = ?,
            next_attempt_at = ?,
            sent_at = ?,
            erro = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, attempts, last_attempt_at, next_attempt_at, sent_at, erro, delivery_id),
    )
    connection.commit()
    return obter_alert_delivery(connection, delivery_id)


def listar_por_cliente(connection: sqlite3.Connection, table: str, cliente_id: str | None) -> list[dict[str, Any]]:
    if cliente_id is None:
        return listar(connection, table)
    if table == "clientes":
        rows = connection.execute("SELECT * FROM clientes WHERE id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [row_to_dict(row) for row in rows]
    if table == "unidades":
        rows = connection.execute("SELECT * FROM unidades WHERE cliente_id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [row_to_dict(row) for row in rows]
    if table == "cameras":
        rows = connection.execute("SELECT * FROM cameras WHERE cliente_id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [camera_public_dict(row) for row in rows]
    if table == "eventos":
        rows = connection.execute("SELECT * FROM eventos WHERE cliente_id = ? ORDER BY criado_em DESC", (cliente_id,)).fetchall()
        return [evento_public_dict(row) for row in rows]
    return listar(connection, table)


def alterar_senha_camera(connection: sqlite3.Connection, camera_id: str, password: str) -> bool:
    cursor = connection.execute(
        """
        UPDATE cameras
        SET rtsp_password = NULL,
            rtsp_password_encrypted = ?
        WHERE id = ?
        """,
        (encrypt_secret(password), camera_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def criar_technical_notice(
    connection: sqlite3.Connection,
    component: str,
    cliente_id: str | None = None,
    camera_id: str | None = None,
    erro: str | None = None,
    inicio: str | None = None,
) -> str:
    existing = connection.execute(
        """
        SELECT id
        FROM technical_notices
        WHERE component = ? AND COALESCE(camera_id, '') = COALESCE(?, '') AND status = 'open'
        LIMIT 1
        """,
        (component, camera_id),
    ).fetchone()
    if existing:
        return str(existing["id"])
    notice_id = new_id("tec")
    connection.execute(
        """
        INSERT INTO technical_notices (id, cliente_id, camera_id, component, inicio, erro)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (notice_id, cliente_id, camera_id, component, inicio or now_iso(), erro),
    )
    connection.commit()
    return notice_id


def fechar_technical_notice(connection: sqlite3.Connection, notice_id: str, fim: str | None = None) -> bool:
    cursor = connection.execute(
        "UPDATE technical_notices SET status = 'closed', fim = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (fim or now_iso(), notice_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def listar_technical_notices(connection: sqlite3.Connection, cliente_id: str | None = None) -> list[dict[str, Any]]:
    if cliente_id:
        rows = connection.execute(
            "SELECT * FROM technical_notices WHERE cliente_id = ? ORDER BY criado_em DESC LIMIT 200",
            (cliente_id,),
        ).fetchall()
    else:
        rows = connection.execute("SELECT * FROM technical_notices ORDER BY criado_em DESC LIMIT 200").fetchall()
    return [row_to_dict(row) for row in rows]


def set_installation_state(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO installation_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, atualizado_em = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    connection.commit()


def get_installation_state(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT key, value FROM installation_state").fetchall()
    return {row["key"]: row["value"] for row in rows}


def normalize_presence_scope(value: str | None) -> str:
    normalized = str(value or "OPERATOR_ZONE").strip().upper()
    if normalized not in {"OPERATOR_ZONE", "OPERATION_AREA"}:
        return "OPERATOR_ZONE"
    return normalized


def machine_monitor_public_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["ativo"] = bool(data["ativo"])
    data["operator_present"] = bool(data.get("operator_present"))
    data["machine_polygon"] = json.loads(data.pop("machine_polygon_json"))
    data["operator_polygon"] = json.loads(data.pop("operator_polygon_json"))
    operation_polygon = data.pop("operation_polygon_json", None)
    data["operation_polygon"] = json.loads(operation_polygon) if operation_polygon else None
    data["presence_scope"] = str(data.get("presence_scope") or "OPERATOR_ZONE").upper()
    indicator = data.pop("indicator_polygon_json", None)
    data["indicator_polygon"] = json.loads(indicator) if indicator else None
    active_calibration = data.pop("active_calibration_json", None)
    stopped_calibration = data.pop("stopped_calibration_json", None)
    data["active_calibration"] = json.loads(active_calibration) if active_calibration else None
    data["stopped_calibration"] = json.loads(stopped_calibration) if stopped_calibration else None
    has_partial_calibration = bool(data["active_calibration"] or data["stopped_calibration"])
    if data.get("calibration_result") == "INVALID" and has_partial_calibration and (not data["active_calibration"] or not data["stopped_calibration"]):
        data["calibration_result"] = "CALIBRATION_REQUIRED"
        data["calibration_status"] = "calibration_pending"
    return data


def criar_machine_monitor(
    connection: sqlite3.Connection,
    client_id: str,
    unit_id: str,
    camera_id: str,
    nome: str,
    machine_polygon: list[dict[str, float]],
    operator_polygon: list[dict[str, float]],
    ativo: bool = True,
    motion_sensitivity: float = 25.0,
    stop_seconds: float = 10.0,
    recovery_seconds: float = 3.0,
    replay_pre_seconds: float = 60.0,
    replay_post_seconds: float = 30.0,
    operator_absence_seconds: float = 30.0,
    stopped_with_operator_seconds: float = 120.0,
    microstop_window_seconds: float = 3600.0,
    microstop_limit: int = 5,
    loss_model: str | None = None,
    loss_per_minute: float | None = None,
    units_per_minute: float | None = None,
    margin_per_unit: float | None = None,
    indicator_polygon: list[dict[str, float]] | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    operation_polygon: list[dict[str, float]] | None = None,
    presence_scope: str = "OPERATOR_ZONE",
) -> str:
    monitor_id = new_id("mach")
    connection.execute(
        """
        INSERT INTO machine_monitors (
            id, client_id, unit_id, camera_id, nome, machine_polygon_json,
            operator_polygon_json, operation_polygon_json, presence_scope, ativo, motion_sensitivity, stop_seconds,
            recovery_seconds, replay_pre_seconds, replay_post_seconds,
            operator_absence_seconds, stopped_with_operator_seconds,
            microstop_window_seconds, microstop_limit, loss_model,
            loss_per_minute, units_per_minute, margin_per_unit, indicator_polygon_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            monitor_id,
            client_id,
            unit_id,
            camera_id,
            nome,
            json.dumps(machine_polygon),
            json.dumps(operator_polygon),
            json.dumps(operation_polygon) if operation_polygon else None,
            normalize_presence_scope(presence_scope),
            1 if ativo else 0,
            motion_sensitivity,
            stop_seconds,
            recovery_seconds,
            replay_pre_seconds,
            replay_post_seconds,
            operator_absence_seconds,
            stopped_with_operator_seconds,
            microstop_window_seconds,
            microstop_limit,
            loss_model,
            loss_per_minute,
            units_per_minute,
            margin_per_unit,
            json.dumps(indicator_polygon) if indicator_polygon else None,
        ),
    )
    from app.operational_context import resolve_context

    context = resolve_context(connection, camera_id=camera_id)
    connection.execute(
        """
        UPDATE machine_monitors
        SET site_id = ?,
            area_context_id = COALESCE(?, ?),
            process_id = COALESCE(?, ?),
            asset_id = COALESCE(?, ?)
        WHERE id = ?
        """,
        (
            context.get("site_id") or unit_id,
            area_context_id,
            context.get("area_context_id"),
            process_id,
            context.get("process_id"),
            asset_id,
            context.get("asset_id"),
            monitor_id,
        ),
    )
    connection.commit()
    return monitor_id


def listar_machine_monitors_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM machine_monitors WHERE camera_id = ? ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [machine_monitor_public_dict(row) for row in rows]


def listar_machine_monitors_ativos_camera(connection: sqlite3.Connection, camera_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM machine_monitors WHERE camera_id = ? AND ativo = 1 ORDER BY criado_em DESC",
        (camera_id,),
    ).fetchall()
    return [machine_monitor_public_dict(row) for row in rows]


def obter_machine_monitor(connection: sqlite3.Connection, monitor_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM machine_monitors WHERE id = ?", (monitor_id,)).fetchone()
    return machine_monitor_public_dict(row) if row else None


def atualizar_machine_monitor(
    connection: sqlite3.Connection,
    monitor_id: str,
    nome: str | None = None,
    machine_polygon: list[dict[str, float]] | None = None,
    operator_polygon: list[dict[str, float]] | None = None,
    operation_polygon: list[dict[str, float]] | None = None,
    presence_scope: str | None = None,
    ativo: bool | None = None,
    motion_sensitivity: float | None = None,
    motion_threshold: float | None = None,
    stop_seconds: float | None = None,
    recovery_seconds: float | None = None,
    calibration_status: str | None = None,
    running_motion: float | None = None,
    stopped_motion: float | None = None,
    active_baseline: float | None = None,
    stopped_baseline: float | None = None,
    active_noise: float | None = None,
    stopped_noise: float | None = None,
    operator_absence_seconds: float | None = None,
    stopped_with_operator_seconds: float | None = None,
    microstop_window_seconds: float | None = None,
    microstop_limit: int | None = None,
    loss_model: str | None = None,
    loss_per_minute: float | None = None,
    units_per_minute: float | None = None,
    margin_per_unit: float | None = None,
    indicator_polygon: list[dict[str, float]] | None = None,
    indicator_on_baseline: float | None = None,
    indicator_off_baseline: float | None = None,
    active_calibration: dict[str, Any] | None = None,
    stopped_calibration: dict[str, Any] | None = None,
    separation_score: float | None = None,
    calibration_result: str | None = None,
    calibration_algorithm_version: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any] | None:
    current = obter_machine_monitor(connection, monitor_id)
    if current is None:
        return None
    connection.execute(
        """
        UPDATE machine_monitors
        SET nome = ?,
            machine_polygon_json = ?,
            operator_polygon_json = ?,
            operation_polygon_json = ?,
            presence_scope = ?,
            ativo = ?,
            motion_sensitivity = ?,
            motion_threshold = COALESCE(?, motion_threshold),
            stop_seconds = ?,
            recovery_seconds = ?,
            calibration_status = COALESCE(?, calibration_status),
            running_motion = COALESCE(?, running_motion),
            stopped_motion = COALESCE(?, stopped_motion),
            active_baseline = COALESCE(?, active_baseline),
            stopped_baseline = COALESCE(?, stopped_baseline),
            active_noise = COALESCE(?, active_noise),
            stopped_noise = COALESCE(?, stopped_noise),
            operator_absence_seconds = ?,
            stopped_with_operator_seconds = ?,
            microstop_window_seconds = ?,
            microstop_limit = ?,
            loss_model = COALESCE(?, loss_model),
            loss_per_minute = COALESCE(?, loss_per_minute),
            units_per_minute = COALESCE(?, units_per_minute),
            margin_per_unit = COALESCE(?, margin_per_unit),
            indicator_polygon_json = COALESCE(?, indicator_polygon_json),
            indicator_on_baseline = COALESCE(?, indicator_on_baseline),
            indicator_off_baseline = COALESCE(?, indicator_off_baseline),
            active_calibration_json = COALESCE(?, active_calibration_json),
            stopped_calibration_json = COALESCE(?, stopped_calibration_json),
            separation_score = COALESCE(?, separation_score),
            calibration_result = COALESCE(?, calibration_result),
            calibration_algorithm_version = COALESCE(?, calibration_algorithm_version),
            site_id = COALESCE(site_id, unit_id),
            area_context_id = COALESCE(?, area_context_id),
            process_id = COALESCE(?, process_id),
            asset_id = COALESCE(?, asset_id),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            nome if nome is not None else current["nome"],
            json.dumps(machine_polygon if machine_polygon is not None else current["machine_polygon"]),
            json.dumps(operator_polygon if operator_polygon is not None else current["operator_polygon"]),
            json.dumps(operation_polygon if operation_polygon is not None else current.get("operation_polygon")) if (operation_polygon is not None or current.get("operation_polygon")) else None,
            normalize_presence_scope(presence_scope if presence_scope is not None else current.get("presence_scope", "OPERATOR_ZONE")),
            1 if (ativo if ativo is not None else current["ativo"]) else 0,
            motion_sensitivity if motion_sensitivity is not None else current["motion_sensitivity"],
            motion_threshold,
            stop_seconds if stop_seconds is not None else current["stop_seconds"],
            recovery_seconds if recovery_seconds is not None else current["recovery_seconds"],
            calibration_status,
            running_motion,
            stopped_motion,
            active_baseline,
            stopped_baseline,
            active_noise,
            stopped_noise,
            operator_absence_seconds if operator_absence_seconds is not None else current.get("operator_absence_seconds", 30.0),
            stopped_with_operator_seconds if stopped_with_operator_seconds is not None else current.get("stopped_with_operator_seconds", 120.0),
            microstop_window_seconds if microstop_window_seconds is not None else current.get("microstop_window_seconds", 3600.0),
            microstop_limit if microstop_limit is not None else current.get("microstop_limit", 5),
            loss_model,
            loss_per_minute,
            units_per_minute,
            margin_per_unit,
            json.dumps(indicator_polygon) if indicator_polygon is not None else None,
            indicator_on_baseline,
            indicator_off_baseline,
            json.dumps(active_calibration, ensure_ascii=False) if active_calibration is not None else None,
            json.dumps(stopped_calibration, ensure_ascii=False) if stopped_calibration is not None else None,
            separation_score,
            calibration_result,
            calibration_algorithm_version,
            area_context_id,
            process_id,
            asset_id,
            monitor_id,
        ),
    )
    connection.commit()
    return obter_machine_monitor(connection, monitor_id)


def registrar_machine_calibration(
    connection: sqlite3.Connection,
    *,
    machine_id: str,
    camera_id: str,
    phase: str,
    samples: list[float],
    stats: dict[str, Any],
    algorithm_version: str,
    region: list[dict[str, float]],
    started_at: str,
    finished_at: str,
) -> str:
    calibration_id = new_id("cal")
    connection.execute(
        """
        INSERT INTO machine_calibrations (
            id, machine_id, camera_id, phase, samples_json, stats_json,
            baseline, algorithm_version, region_json, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            calibration_id,
            machine_id,
            camera_id,
            phase,
            json.dumps(samples),
            json.dumps(stats, ensure_ascii=False),
            stats.get("mean"),
            algorithm_version,
            json.dumps(region),
            started_at,
            finished_at,
        ),
    )
    connection.commit()
    return calibration_id


def excluir_machine_monitor(connection: sqlite3.Connection, monitor_id: str) -> bool:
    cursor = connection.execute("DELETE FROM machine_monitors WHERE id = ?", (monitor_id,))
    connection.commit()
    return cursor.rowcount > 0


def atualizar_machine_monitor_estado(
    connection: sqlite3.Connection,
    monitor_id: str,
    state: str,
    motion: float | None,
    operator_present: bool,
    changed_at: str | None = None,
    confidence: float | None = None,
    reason: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE machine_monitors
        SET current_state = ?,
            current_motion = ?,
            operator_present = ?,
            confidence = COALESCE(?, confidence),
            state_reason = COALESCE(?, state_reason),
            last_state_change = COALESCE(?, last_state_change),
            machine_state_since = COALESCE(?, machine_state_since),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (state, motion, 1 if operator_present else 0, confidence, reason, changed_at, changed_at, monitor_id),
    )
    connection.commit()


def criar_evento_machine_stoppage(
    connection: sqlite3.Connection,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    machine_monitor_id: str,
    inicio: str,
    motion_level: float,
    operator_present_start: bool,
    confidence: float,
    midia_path: str | None,
    track_ids: list[int],
) -> str:
    existing = connection.execute(
        """
        SELECT id
        FROM eventos
        WHERE machine_monitor_id = ?
          AND tipo = ?
          AND status = 'open'
        ORDER BY inicio DESC, criado_em DESC
        LIMIT 1
        """,
        (machine_monitor_id, "machine_stoppage"),
    ).fetchone()
    if existing:
        return str(existing["id"])
    evento_id = new_id("evt")
    event_uuid = new_event_uuid()
    taxonomy = classify_event_type("machine_stoppage")
    connection.execute(
        """
        INSERT INTO eventos (
            id, event_uuid, cliente_id, unidade_id, camera_id, machine_monitor_id, tipo,
            severidade, status, inicio, motion_level, operator_present_start,
            operador_presente, confianca, midia_path, track_ids_json,
            operator_present_seconds, operator_absent_seconds, max_people, event_family, event_subtype
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento_id,
            event_uuid,
            cliente_id,
            unidade_id,
            camera_id,
            machine_monitor_id,
            "machine_stoppage",
            "medium",
            "open",
            inicio,
            motion_level,
            1 if operator_present_start else 0,
            1 if operator_present_start else 0,
            confidence,
            midia_path,
            json.dumps(sorted(set(track_ids))),
            0.0,
            0.0,
            len(set(track_ids)),
            taxonomy.event_family,
            taxonomy.event_subtype,
        ),
    )
    from app.operational_context import apply_context_to_event

    apply_context_to_event(connection, evento_id, camera_id=camera_id, machine_monitor_id=machine_monitor_id)
    _enqueue_evento_cloud(
        connection,
        event_uuid=event_uuid,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        camera_id=camera_id,
        tipo="machine_stoppage",
        inicio=inicio,
        operador_presente=operator_present_start,
        confianca=confidence,
        midia_path=midia_path,
        metadata={
            "machine_monitor_id": machine_monitor_id,
            "motion_level": motion_level,
            "track_ids": sorted(set(track_ids)),
        },
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()
    return evento_id


def criar_evento_machine_operational(
    connection: sqlite3.Connection,
    *,
    cliente_id: str,
    unidade_id: str,
    camera_id: str,
    machine_monitor_id: str,
    tipo: str,
    inicio: str,
    motion_level: float,
    operator_present_start: bool,
    confidence: float,
    midia_path: str | None,
    track_ids: list[int],
    severidade: str = "medium",
    metadata: dict[str, Any] | None = None,
) -> str:
    existing = connection.execute(
        """
        SELECT id
        FROM eventos
        WHERE machine_monitor_id = ?
          AND tipo = ?
          AND status = 'open'
        ORDER BY inicio DESC, criado_em DESC
        LIMIT 1
        """,
        (machine_monitor_id, tipo),
    ).fetchone()
    if existing:
        return str(existing["id"])
    evento_id = new_id("evt")
    event_uuid = new_event_uuid()
    metadata = metadata or {}
    taxonomy = classify_event_type(tipo)
    connection.execute(
        """
        INSERT INTO eventos (
            id, event_uuid, cliente_id, unidade_id, camera_id, machine_monitor_id, tipo,
            severidade, status, inicio, motion_level, operator_present_start,
            operador_presente, confianca, midia_path, track_ids_json,
            operator_present_seconds, operator_absent_seconds, max_people, metadata_json,
            event_family, event_subtype
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento_id,
            event_uuid,
            cliente_id,
            unidade_id,
            camera_id,
            machine_monitor_id,
            tipo,
            severidade,
            "open",
            inicio,
            motion_level,
            1 if operator_present_start else 0,
            1 if operator_present_start else 0,
            confidence,
            midia_path,
            json.dumps(sorted(set(track_ids))),
            0.0,
            0.0,
            len(set(track_ids)),
            json.dumps(metadata, ensure_ascii=False),
            taxonomy.event_family,
            taxonomy.event_subtype,
        ),
    )
    from app.operational_context import apply_context_to_event

    apply_context_to_event(connection, evento_id, camera_id=camera_id, machine_monitor_id=machine_monitor_id)
    _enqueue_evento_cloud(
        connection,
        event_uuid=event_uuid,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        camera_id=camera_id,
        tipo=tipo,
        inicio=inicio,
        operador_presente=operator_present_start,
        confianca=confidence,
        midia_path=midia_path,
        metadata={
            **metadata,
            "machine_monitor_id": machine_monitor_id,
            "motion_level": motion_level,
            "track_ids": sorted(set(track_ids)),
        },
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()
    return evento_id


def atualizar_evento_machine_stoppage(
    connection: sqlite3.Connection,
    evento_id: str,
    duracao: float,
    motion_level: float,
    operator_present_seconds: float,
    operator_absent_seconds: float,
    max_people: int,
    track_ids: list[int],
) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET duracao = ?,
            motion_level = ?,
            operator_present_seconds = ?,
            operator_absent_seconds = ?,
            max_people = ?,
            track_ids_json = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (duracao, motion_level, operator_present_seconds, operator_absent_seconds, max_people, json.dumps(sorted(set(track_ids))), evento_id),
    )
    connection.commit()


def fechar_evento_machine_stoppage(connection: sqlite3.Connection, evento_id: str, fim: str, duracao: float) -> None:
    connection.execute(
        """
        UPDATE eventos
        SET status = 'closed', fim = ?, duracao = ?, atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'open'
        """,
        (fim, duracao, evento_id),
    )
    atualizar_outbox_evento(connection, evento_id)
    connection.commit()


def fechar_eventos_machine_interrompidos(connection: sqlite3.Connection) -> list[str]:
    """Close machine events left open by a previous runtime process.

    The stored duration is the last duration actually observed by the runtime.
    We intentionally do not extend it using wall-clock time while the Edge was
    offline, because that would fabricate hours of absence/stoppage.
    """
    rows = connection.execute(
        """
        SELECT id
        FROM eventos
        WHERE status = 'open'
          AND machine_monitor_id IS NOT NULL
        """
    ).fetchall()
    event_ids = [str(row["id"]) for row in rows]
    if not event_ids:
        return []
    placeholders = ",".join("?" for _ in event_ids)
    connection.execute(
        f"""
        UPDATE eventos
        SET status = 'closed',
            fim = COALESCE(atualizado_em, inicio),
            duracao = COALESCE(duracao, 0),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders})
          AND status = 'open'
        """,
        event_ids,
    )
    for event_id in event_ids:
        atualizar_outbox_evento(connection, event_id)
    connection.commit()
    return event_ids


def atualizar_evento_replay(
    connection: sqlite3.Connection,
    evento_id: str,
    replay_path: str | None = None,
    replay_error: str | None = None,
) -> None:
    connection.execute(
        "UPDATE eventos SET replay_path = COALESCE(?, replay_path), replay_error = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (replay_path, replay_error, evento_id),
    )
    connection.commit()


def classificar_evento(
    connection: sqlite3.Connection,
    evento_id: str,
    cause_category: str,
    cause_notes: str | None,
    classified_by: str | None,
    classified_at: str,
) -> dict[str, Any] | None:
    from app.event_workflow import update_human_context

    return update_human_context(
        connection,
        evento_id,
        confirmed_cause=cause_category,
        human_notes=cause_notes,
        actor=classified_by,
        at=classified_at,
    )
