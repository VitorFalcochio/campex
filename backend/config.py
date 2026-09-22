from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#") or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv()


def _env_list(name: str, default: str) -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _env_mapping(name: str, default: str = "") -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in _env_list(name, default):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            mapping[key] = value
    return mapping


@dataclass(frozen=True)
class Settings:
    environment: str
    service_name: str
    version: str
    log_level: str
    database_url: str
    frontend_origins: list[str]
    camera_reconnect_seconds: float
    camera_stale_seconds: float
    camera_offline_seconds: float
    camera_read_failure_limit: int
    camera_test_timeout_seconds: float
    vision_enabled: bool
    vision_detector: str
    vision_device: str
    vision_fps: float
    vision_confidence: float
    vision_video_loop: bool
    api_token: str | None = None
    vision_model: str = "yolo11n.pt"
    vision_input_size: int = 960
    vision_full_scan_seconds: float = 6.0
    vision_tracker_lost_buffer: int = 30
    machine_active_seconds: float = 3.0
    machine_stopped_seconds: float = 20.0
    stream_fps: float = 8.0
    stream_max_width: int = 960
    stream_jpeg_quality: int = 68
    intelligence_enabled: bool = True
    intelligence_default_organization_id: str = "default"
    intelligence_allowed_organization_ids: list[str] | None = None
    intelligence_organization_tokens: dict[str, str] | None = None
    nvidia_api_key: str | None = None
    nemotron_base_url: str = "https://integrate.api.nvidia.com/v1"
    nemotron_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    nemotron_timeout_seconds: float = 20.0
    nemotron_temperature: float = 0.2
    nemotron_top_p: float = 0.7
    nemotron_max_tokens: int = 700
    telegram_bot_token: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "CAMPEX"
    smtp_use_tls: bool = True
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 6000
    rate_limit_window_seconds: float = 60.0
    rate_limit_unauthorized_only: bool = False
    video_upload_dir: str = "./storage/video_uploads"
    video_max_upload_mb: int = 250
    video_analysis_fps: float = 2.0
    video_temporary_retention_hours: float = 24.0
    video_debug_overlay: bool = False
    movement_threshold: float = 0.025
    stationary_threshold_seconds: float = 30.0
    long_presence_threshold_seconds: float = 600.0
    zone_idle_threshold_seconds: float = 300.0
    crowding_threshold: int = 8
    line_crossing_cooldown_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.camera_reconnect_seconds < 0:
            raise ValueError("CAMERA_RECONNECT_SECONDS must be non-negative.")
        if self.camera_stale_seconds <= 0:
            raise ValueError("CAMERA_STALE_SECONDS must be greater than zero.")
        if self.camera_offline_seconds <= self.camera_stale_seconds:
            raise ValueError("CAMERA_OFFLINE_SECONDS must be greater than CAMERA_STALE_SECONDS.")
        if self.camera_read_failure_limit < 1:
            raise ValueError("CAMERA_READ_FAILURE_LIMIT must be at least 1.")
        if self.camera_test_timeout_seconds <= 0:
            raise ValueError("CAMERA_TEST_TIMEOUT_SECONDS must be greater than zero.")
        if self.vision_fps <= 0:
            raise ValueError("VISION_FPS must be greater than zero.")
        if not 0.0 <= self.vision_confidence <= 1.0:
            raise ValueError("VISION_CONFIDENCE must be between 0 and 1.")
        if self.vision_input_size < 320:
            raise ValueError("VISION_INPUT_SIZE must be at least 320.")
        if self.vision_full_scan_seconds <= 0:
            raise ValueError("VISION_FULL_SCAN_SECONDS must be greater than zero.")
        if self.vision_tracker_lost_buffer < 1:
            raise ValueError("VISION_TRACKER_LOST_BUFFER must be at least 1.")
        if self.machine_active_seconds <= 0:
            raise ValueError("MACHINE_ACTIVE_SECONDS must be greater than zero.")
        if self.machine_stopped_seconds <= self.machine_active_seconds:
            raise ValueError("MACHINE_STOPPED_SECONDS must be greater than MACHINE_ACTIVE_SECONDS.")
        if self.stream_fps <= 0:
            raise ValueError("STREAM_FPS must be greater than zero.")
        if self.stream_max_width < 240:
            raise ValueError("STREAM_MAX_WIDTH must be at least 240.")
        if not 30 <= self.stream_jpeg_quality <= 95:
            raise ValueError("STREAM_JPEG_QUALITY must be between 30 and 95.")
        if not self.intelligence_default_organization_id:
            raise ValueError("CAMPEX_DEFAULT_ORGANIZATION_ID must not be empty.")
        if self.nemotron_timeout_seconds <= 0:
            raise ValueError("NEMOTRON_TIMEOUT_SECONDS must be greater than zero.")
        if not 0.0 <= self.nemotron_temperature <= 2.0:
            raise ValueError("NEMOTRON_TEMPERATURE must be between 0 and 2.")
        if not 0.0 <= self.nemotron_top_p <= 1.0:
            raise ValueError("NEMOTRON_TOP_P must be between 0 and 1.")
        if self.nemotron_max_tokens < 1:
            raise ValueError("NEMOTRON_MAX_TOKENS must be at least 1.")
        if self.video_max_upload_mb < 1:
            raise ValueError("VIDEO_MAX_UPLOAD_MB must be at least 1.")
        if self.video_analysis_fps <= 0:
            raise ValueError("VIDEO_ANALYSIS_FPS must be greater than zero.")
        if self.video_temporary_retention_hours <= 0:
            raise ValueError("VIDEO_TEMPORARY_RETENTION_HOURS must be greater than zero.")
        if self.movement_threshold <= 0:
            raise ValueError("MOVEMENT_THRESHOLD must be greater than zero.")
        if self.stationary_threshold_seconds <= 0:
            raise ValueError("STATIONARY_THRESHOLD_SECONDS must be greater than zero.")
        if self.long_presence_threshold_seconds <= 0:
            raise ValueError("LONG_PRESENCE_THRESHOLD_SECONDS must be greater than zero.")
        if self.zone_idle_threshold_seconds <= 0:
            raise ValueError("ZONE_IDLE_THRESHOLD_SECONDS must be greater than zero.")
        if self.crowding_threshold < 1:
            raise ValueError("CROWDING_THRESHOLD must be at least 1.")
        if self.line_crossing_cooldown_seconds < 0:
            raise ValueError("LINE_CROSSING_COOLDOWN_SECONDS must be non-negative.")

    @property
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Sprint 0 supports only sqlite:/// DATABASE_URL values.")

        raw_path = self.database_url.removeprefix(prefix)
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = ROOT_DIR / db_path
        return db_path.resolve()

    @classmethod









    def from_env(cls) -> "Settings":
        return cls(
            environment=os.getenv("CAMPEX_ENV", "development"),
            service_name=os.getenv("CAMPEX_SERVICE_NAME", "campex"),
            version=os.getenv("CAMPEX_VERSION", "0.1.0"),
            log_level=os.getenv("CAMPEX_LOG_LEVEL", "INFO").upper(),
            database_url=os.getenv(
                "DATABASE_URL", "sqlite:///./storage/campex_dev.sqlite3"
            ),
            frontend_origins=_env_list(
                "CAMPEX_FRONTEND_ORIGINS",
                "http://127.0.0.1:5174,http://localhost:5174,http://127.0.0.1:5500,http://localhost:5500",
            ),
            camera_reconnect_seconds=float(os.getenv("CAMERA_RECONNECT_SECONDS", "5")),
            camera_stale_seconds=float(os.getenv("CAMERA_STALE_SECONDS", "10")),
            camera_offline_seconds=float(os.getenv("CAMERA_OFFLINE_SECONDS", "30")),
            camera_read_failure_limit=int(os.getenv("CAMERA_READ_FAILURE_LIMIT", "3")),
            camera_test_timeout_seconds=float(
                os.getenv("CAMERA_TEST_TIMEOUT_SECONDS", "5")
            ),
            vision_enabled=os.getenv("VISION_ENABLED", "true").lower()
            in {"1", "true", "yes", "on"},
            vision_detector=os.getenv("VISION_DETECTOR", "yolo").lower(),
            vision_model=os.getenv("VISION_MODEL", "yolo11n.pt"),
            vision_device=os.getenv("VISION_DEVICE", "auto").lower(),
            vision_fps=float(os.getenv("VISION_FPS", "5")),
            vision_confidence=float(
                os.getenv(
                    "VISION_CONFIDENCE_THRESHOLD",
                    os.getenv("VISION_CONFIDENCE", "0.35"),
                )
            ),
            vision_input_size=int(os.getenv("VISION_INPUT_SIZE", "960")),
            vision_video_loop=os.getenv("VISION_VIDEO_LOOP", "true").lower()
            in {"1", "true", "yes", "on"},
            api_token=os.getenv("CAMPEX_API_TOKEN") or None,
            vision_full_scan_seconds=float(
                os.getenv("VISION_FULL_SCAN_SECONDS", "6")
            ),
            vision_tracker_lost_buffer=int(
                os.getenv("VISION_TRACKER_LOST_BUFFER", "30")
            ),
            machine_active_seconds=float(os.getenv("MACHINE_ACTIVE_SECONDS", "3")),
            machine_stopped_seconds=float(os.getenv("MACHINE_STOPPED_SECONDS", "20")),
            stream_fps=float(os.getenv("STREAM_FPS", "8")),
            stream_max_width=int(os.getenv("STREAM_MAX_WIDTH", "960")),
            stream_jpeg_quality=int(os.getenv("STREAM_JPEG_QUALITY", "68")),
            intelligence_enabled=os.getenv("INTELLIGENCE_ENABLED", "true").lower()
            in {"1", "true", "yes", "on"},
            intelligence_default_organization_id=os.getenv(
                "CAMPEX_DEFAULT_ORGANIZATION_ID", "default"
            ),
            intelligence_allowed_organization_ids=_env_list(
                "CAMPEX_ALLOWED_ORGANIZATION_IDS",
                os.getenv("CAMPEX_DEFAULT_ORGANIZATION_ID", "default"),
            ),
            intelligence_organization_tokens=_env_mapping("CAMPEX_ORGANIZATION_TOKENS"),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY") or None,
            nemotron_base_url=os.getenv(
                "NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ).rstrip("/"),
            nemotron_model=os.getenv(
                "NEMOTRON_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"
            ),
            nemotron_timeout_seconds=float(os.getenv("NEMOTRON_TIMEOUT_SECONDS", "20")),
            nemotron_temperature=float(os.getenv("NEMOTRON_TEMPERATURE", "0.2")),
            nemotron_top_p=float(os.getenv("NEMOTRON_TOP_P", "0.7")),
            nemotron_max_tokens=int(os.getenv("NEMOTRON_MAX_TOKENS", "700")),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            smtp_host=os.getenv("SMTP_HOST") or None,
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME") or None,
            smtp_password=os.getenv("SMTP_PASSWORD") or None,
            smtp_from_email=os.getenv("SMTP_FROM_EMAIL") or None,
            smtp_from_name=os.getenv("SMTP_FROM_NAME", "CAMPEX"),
            smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower()
            in {"1", "true", "yes", "on"},
            rate_limit_enabled=os.getenv("CAMPEX_RATE_LIMIT_ENABLED", "true").lower()
            in {"1", "true", "yes", "on"},
            rate_limit_requests=int(os.getenv("CAMPEX_RATE_LIMIT_REQUESTS", "6000")),
            rate_limit_window_seconds=float(
                os.getenv("CAMPEX_RATE_LIMIT_WINDOW_SECONDS", "60")
            ),
            video_upload_dir=os.getenv("VIDEO_UPLOAD_DIR", "./storage/video_uploads"),
            video_max_upload_mb=int(os.getenv("VIDEO_MAX_UPLOAD_MB", "250")),
            video_analysis_fps=float(os.getenv("VIDEO_ANALYSIS_FPS", "5")),
            video_temporary_retention_hours=float(
                os.getenv("VIDEO_TEMPORARY_RETENTION_HOURS", "24")
            ),
            video_debug_overlay=os.getenv("VIDEO_DEBUG_OVERLAY", "false").lower()
            in {"1", "true", "yes", "on"},
            movement_threshold=float(os.getenv("MOVEMENT_THRESHOLD", "0.025")),
            stationary_threshold_seconds=float(
                os.getenv("STATIONARY_THRESHOLD_SECONDS", "30")
            ),
            long_presence_threshold_seconds=float(
                os.getenv("LONG_PRESENCE_THRESHOLD_SECONDS", "600")
            ),
            zone_idle_threshold_seconds=float(
                os.getenv("ZONE_IDLE_THRESHOLD_SECONDS", "300")
            ),
            crowding_threshold=int(os.getenv("CROWDING_THRESHOLD", "8")),
            line_crossing_cooldown_seconds=float(
                os.getenv("LINE_CROSSING_COOLDOWN_SECONDS", "8")
            ),
        )


def get_settings() -> Settings:
    return Settings.from_env()
