from backend.cameras.repository import CameraRepository
from backend.cameras.base import CameraConfig
from backend.cameras.factory import create_camera_source
from backend.cameras.opencv_source import IPCameraSource, RTSPSource
from backend.database.db import initialize_database
from tests.helpers import make_settings


def test_camera_model_persists_minimum_fields(tmp_path):
    settings = make_settings(tmp_path / "repo.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)

    camera = repository.create(
        name="Entrada",
        area_id=None,
        source_type="webcam",
        source_uri="0",
        enabled=True,
        vision_enabled=False,
    )

    assert camera.id.startswith("cam_")
    assert camera.name == "Entrada"
    assert camera.source_type == "webcam"
    assert camera.status == "OFFLINE"

    updated = repository.update(camera.id, {"enabled": False, "name": "Entrada 2"})

    assert updated is not None
    assert updated.enabled is False
    assert updated.name == "Entrada 2"
    assert repository.delete(camera.id) is True
    assert repository.get(camera.id) is None


def test_network_camera_sources_are_supported(tmp_path):
    settings = make_settings(tmp_path / "repo.sqlite3")

    rtsp_source = create_camera_source(
        CameraConfig(
            id="cam_rtsp",
            source_type="rtsp",
            source_uri="rtsp://admin:secret@192.168.1.10:554/stream1",
        ),
        settings=settings,
    )
    ip_source = create_camera_source(
        CameraConfig(
            id="cam_ip",
            source_type="ip_camera",
            source_uri="http://192.168.1.20:8080/video",
        ),
        settings=settings,
    )

    assert isinstance(rtsp_source, RTSPSource)
    assert isinstance(ip_source, IPCameraSource)


def test_ip_camera_model_persists_source_type(tmp_path):
    settings = make_settings(tmp_path / "repo.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)

    camera = repository.create(
        name="IP Patio",
        area_id="patio",
        source_type="ip_camera",
        source_uri="http://192.168.1.20:8080/video",
        enabled=True,
        vision_enabled=True,
    )

    assert camera.source_type == "ip_camera"
    assert camera.source_uri == "http://192.168.1.20:8080/video"
