from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from edge_agent.camera_connector import CameraSource, UniversalCameraConnector, safe_source_ref


@dataclass
class CameraCheckResult:
    conexao_realizada: bool
    video_recebido: bool
    resolucao: str | None
    fps: float | None
    tipo_conexao: str
    compativel: bool
    motivo_erro: str | None
    referencia_segura: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_camera(source: str, timeout_seconds: float = 5.0) -> CameraCheckResult:
    camera = CameraSource(camera_id="check", source=source)
    connector = UniversalCameraConnector(camera)
    started = time.monotonic()
    try:
        if not connector.open():
            return CameraCheckResult(
                conexao_realizada=False,
                video_recebido=False,
                resolucao=None,
                fps=None,
                tipo_conexao=camera.source_type.value,
                compativel=False,
                motivo_erro=connector.info.error,
                referencia_segura=safe_source_ref(source),
            )
        while time.monotonic() - started <= timeout_seconds:
            ok, frame = connector.capture.read() if connector.capture else (False, None)
            if ok and frame is not None:
                height, width = frame.shape[:2]
                fps = connector.info.fps
                return CameraCheckResult(
                    conexao_realizada=True,
                    video_recebido=True,
                    resolucao=f"{width}x{height}",
                    fps=fps,
                    tipo_conexao=camera.source_type.value,
                    compativel=True,
                    motivo_erro=None,
                    referencia_segura=safe_source_ref(source),
                )
        return CameraCheckResult(
            conexao_realizada=True,
            video_recebido=False,
            resolucao=None,
            fps=connector.info.fps,
            tipo_conexao=camera.source_type.value,
            compativel=False,
            motivo_erro="Fonte abriu, mas nao entregou frames dentro do tempo limite.",
            referencia_segura=safe_source_ref(source),
        )
    except Exception as exc:
        return CameraCheckResult(
            conexao_realizada=False,
            video_recebido=False,
            resolucao=None,
            fps=None,
            tipo_conexao=camera.source_type.value,
            compativel=False,
            motivo_erro=str(exc),
            referencia_segura=safe_source_ref(source),
        )
    finally:
        connector.close()

