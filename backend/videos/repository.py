from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.database.db import connect
from backend.videos.models import AnalysisJob, AnalysisStatus


class VideoAnalysisRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(self, job: AnalysisJob) -> None:
        with connect(self.settings.sqlite_path) as connection:
            connection.execute(
                """
                INSERT INTO video_analyses (
                    id, organization_id, original_filename, stored_filename, storage_path,
                    content_type, file_size, status, progress
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.analysis_id,
                    job.organization_id,
                    job.original_filename,
                    job.stored_filename,
                    str(job.storage_path),
                    job.content_type,
                    job.file_size,
                    job.status.value,
                    job.progress,
                ),
            )
            connection.commit()

    def update(self, analysis_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        if fields.get("status") == AnalysisStatus.COMPLETED:
            fields["completed_at"] = _now()
        normalized = {key: _encode(value) for key, value in fields.items()}
        assignments = ", ".join(f"{key} = ?" for key in normalized)
        with connect(self.settings.sqlite_path) as connection:
            connection.execute(
                f"UPDATE video_analyses SET {assignments} WHERE id = ?",
                (*normalized.values(), analysis_id),
            )
            connection.commit()

    def get(self, analysis_id: str, organization_id: str) -> dict[str, Any] | None:
        with connect(self.settings.sqlite_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM video_analyses
                WHERE id = ? AND organization_id = ?
                """,
                (analysis_id, organization_id),
            ).fetchone()
        return _row(row) if row else None

    def list(self, organization_id: str, limit: int = 25) -> list[dict[str, Any]]:
        with connect(self.settings.sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM video_analyses
                WHERE organization_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (organization_id, limit),
            ).fetchall()
        return [_row(row) for row in rows]


def _encode(value: Any) -> Any:
    if isinstance(value, AnalysisStatus):
        return value.value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Path):
        return str(value)
    return value


def _decode(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "analysis_id": row["id"],
        "organization_id": row["organization_id"],
        "original_filename": row["original_filename"],
        "stored_filename": row["stored_filename"],
        "storage_path": row["storage_path"],
        "content_type": row["content_type"],
        "file_size": row["file_size"],
        "status": row["status"],
        "progress": row["progress"],
        "error": row["error"],
        "source": _decode(row["source_json"], None),
        "metrics": _decode(row["metrics_json"], None),
        "events": _decode(row["events_json"], []),
        "tracks": _decode(row["tracks_json"], []),
        "detections": _decode(row["detections_json"], []),
        "insight": _decode(row["insight_json"], None),
        "debug_video_path": row["debug_video_path"] if "debug_video_path" in row.keys() else None,
        "debug_video": _debug_video(row),
        "runtime": _decode(row["runtime_json"], None) if "runtime_json" in row.keys() else None,
        "ai": _decode(row["ai_json"], None) if "ai_json" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _debug_video(row) -> dict[str, Any] | None:
    if "debug_video_path" not in row.keys() or not row["debug_video_path"]:
        return None
    return {
        "path": row["debug_video_path"],
        "url": f"/api/v1/videos/{row['id']}/debug-video",
    }
