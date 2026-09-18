from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile

from backend.config import ROOT_DIR, Settings
from backend.integrations.nemotron import NemotronClient
from backend.services.intelligence.exceptions import IntelligenceError
from backend.services.intelligence.models import IntelligenceRequest
from backend.services.intelligence.service import CampexIntelligenceService
from backend.vision.detector import create_detector
from backend.videos.models import AnalysisJob, AnalysisStatus
from backend.videos.pipeline import InvalidVideoError, VideoAnalysisPipeline
from backend.videos.repository import VideoAnalysisRepository


logger = logging.getLogger("campex.videos")


class VideoUploadError(ValueError):
    pass


class VideoAnalysisService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = VideoAnalysisRepository(settings)

    def enqueue_upload(self, upload: UploadFile, organization_id: str) -> dict:
        analysis_id = uuid.uuid4().hex
        original = _safe_name(upload.filename or "video.mp4")
        content_type = upload.content_type or ""
        if not original.lower().endswith(".mp4"):
            raise VideoUploadError("Only .mp4 files are supported.")
        if content_type and content_type not in {"video/mp4", "application/octet-stream"}:
            raise VideoUploadError("Invalid MIME type for MP4 upload.")

        upload_dir = _upload_dir(self.settings)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored = f"{analysis_id}-{original}"
        target = (upload_dir / stored).resolve()
        if upload_dir.resolve() not in target.parents:
            raise VideoUploadError("Invalid upload path.")

        max_bytes = self.settings.video_max_upload_mb * 1024 * 1024
        size = _copy_limited(upload.file, target, max_bytes)
        job = AnalysisJob(
            analysis_id=analysis_id,
            organization_id=organization_id,
            original_filename=original,
            stored_filename=stored,
            storage_path=target,
            content_type=content_type,
            file_size=size,
        )
        self.repository.create(job)
        threading.Thread(
            target=self._run_job,
            args=(job,),
            name=f"campex-video-analysis-{analysis_id}",
            daemon=True,
        ).start()
        return self.repository.get(analysis_id, organization_id)

    def get(self, analysis_id: str, organization_id: str) -> dict | None:
        return self.repository.get(analysis_id, organization_id)

    def list(self, organization_id: str) -> list[dict]:
        return self.repository.list(organization_id)

    def _run_job(self, job: AnalysisJob) -> None:
        try:
            self.repository.update(job.analysis_id, status=AnalysisStatus.PROCESSING, progress=1)
            detector = create_detector(self.settings)
            pipeline = VideoAnalysisPipeline(self.settings, detector)
            result = pipeline.analyze(
                job.storage_path,
                job.original_filename,
                progress_callback=lambda progress, **fields: self.repository.update(
                    job.analysis_id,
                    progress=progress,
                    **({"source_json": fields["source"]} if "source" in fields else {}),
                ),
            )
            self.repository.update(
                job.analysis_id,
                status=AnalysisStatus.GENERATING_INSIGHTS,
                progress=95,
                source_json=result["source"],
                metrics_json=result["metrics"],
                events_json=result["events"],
                tracks_json=result["tracks"],
                detections_json=result["detections"],
            )
            insight = self._generate_insight(job.organization_id, result["operational_context"])
            self.repository.update(
                job.analysis_id,
                status=AnalysisStatus.COMPLETED,
                progress=100,
                insight_json=insight,
            )
        except (InvalidVideoError, VideoUploadError) as exc:
            self.repository.update(
                job.analysis_id,
                status=AnalysisStatus.FAILED,
                progress=100,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("[videos] analysis failed", extra={"analysis_id": job.analysis_id})
            self.repository.update(
                job.analysis_id,
                status=AnalysisStatus.FAILED,
                progress=100,
                error="Video analysis failed. See server logs for details.",
            )

    def _generate_insight(self, organization_id: str, context: dict) -> dict:
        fallback = {
            "summary": "A análise visual foi concluída, mas a interpretação por IA não está disponível.",
            "observations": [],
            "attention_points": [],
            "metrics_highlights": [],
            "limitations": ["Nemotron indisponível ou não configurado."],
        }
        try:
            response = CampexIntelligenceService(NemotronClient(self.settings)).ask(
                IntelligenceRequest(
                    organization_id=organization_id,
                    query=(
                        "Return a concise operational analysis in Portuguese. "
                        "Separate observed facts, calculated metrics, interpretation, and attention points."
                    ),
                    context=context,
                )
            )
        except IntelligenceError:
            return fallback
        return {
            "summary": response.answer,
            "observations": [],
            "attention_points": [],
            "metrics_highlights": [],
            "limitations": response.limitations,
            "model": response.model,
        }


def _safe_name(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "video.mp4"


def _upload_dir(settings: Settings) -> Path:
    path = Path(settings.video_upload_dir)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def _copy_limited(source: BinaryIO, target: Path, max_bytes: int) -> int:
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise VideoUploadError("Uploaded video exceeds the configured size limit.")
                output.write(chunk)
        if total == 0:
            raise VideoUploadError("Uploaded file is empty.")
        return total
    except Exception:
        target.unlink(missing_ok=True)
        raise
