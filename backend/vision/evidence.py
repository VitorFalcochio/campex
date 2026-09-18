from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

from backend.config import ROOT_DIR
from backend.events.models import Event
from backend.vision.models import TrackedObject
from backend.vision.overlay import OverlayRenderer


class EvidenceRecorder:
    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir or ROOT_DIR / "storage" / "evidence"
        self._overlay = OverlayRenderer()

    def record(
        self,
        *,
        event: Event,
        frame: Any,
        objects: list[TrackedObject],
        frame_at: datetime,
    ) -> dict:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        event_dir = self.storage_dir / event.id
        event_dir.mkdir(parents=True, exist_ok=True)

        clean_path = event_dir / "frame.jpg"
        overlay_path = event_dir / "overlay.jpg"
        metadata_path = event_dir / "metadata.json"

        cv2.imwrite(str(clean_path), frame)
        overlay = self._overlay.render(frame, objects)
        cv2.imwrite(str(overlay_path), overlay)

        payload = {
            "event_id": event.id,
            "event_type": event.type,
            "camera_id": event.camera_id,
            "zone_id": event.zone_id,
            "track_id": event.track_id,
            "severity": event.severity,
            "frame_at": frame_at.isoformat(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "objects": [obj.as_dict() for obj in objects],
        }
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return {
            "evidence_dir": str(event_dir.relative_to(ROOT_DIR)),
            "snapshot_path": str(clean_path.relative_to(ROOT_DIR)),
            "overlay_path": str(overlay_path.relative_to(ROOT_DIR)),
            "evidence_metadata_path": str(metadata_path.relative_to(ROOT_DIR)),
        }
