# CAMPEX Sprint 2 — Vision Core V1

## 1. Arquitetura

```
Câmera (CameraSource)
  ↓
Frame (numpy.ndarray)
  ↓
VisionEngine (thread scheduler)
  ↓
VisionSession (per-camera state)
  ↓
RFDETRDetector.detect(frame) → List[Detection]
  ↓
ByteTrackTracker.update(detections) → List[TrackedObject]
  ↓
MJPEG Stream (GET /api/v1/cameras/{id}/stream)
  +
JSON overlay data (GET /api/v1/cameras/{id}/vision/objects)
```

### Camadas

| Camada          | Módulo                  | Responsabilidade                         |
|-----------------|-------------------------|------------------------------------------|
| Camera Source   | `backend/cameras/`      | Abrir/leitura de frames via OpenCV      |
| Vision Engine   | `backend/vision/engine.py`| Scheduler de frames + gerenciamento de sessões |
| Detector        | `backend/vision/detector.py`| Interface abstrata + implementação RF-DETR |
| Tracker         | `backend/vision/tracker.py`| Interface abstrata + implementação ByteTrack |
| Overlay         | `backend/vision/overlay.py`| Desenhar bounding boxes no frame         |
| API             | `backend/api/vision.py`  | Endpoints REST + streaming MJPEG         |
| Frontend        | `frontend/js/app.js`     | Página "Ao vivo" + controles             |

## 2. Dependências

Adicionadas nesta Sprint:

- `rfdetr==1.10.1` — RF-DETR Nano detector
  - Depende transitivamente de: `torch`, `transformers`, `supervision`, `torchvision`
- `torch` (instalado via rfdetr)
- `supervision` (instalado via rfdetr — usado internamente pelo rfdetr)

Já existentes preservadas:

- `fastapi==0.116.1`, `uvicorn==0.35.0`
- `opencv-python-headless==4.12.0.88`
- `pytest==8.4.1`, `httpx==0.28.1`

## 3. Detector (VisionDetector)

### Interface

```python
class VisionDetector(ABC):
    name: str              # nome legível
    device: str            # "CPU" ou "CUDA"

    def load(self) -> None  # carrega modelo UMA VEZ
    def detect(self, frame) -> tuple[list[Detection], float]  # (detections, inference_ms)
```

### RFDETRDetector

- Usa `RFDETRNano` do pacote `rfdetr`.
- Modelo carregado **uma única vez** via `load()` (idempotente).
- Device detectado automaticamente: `VISION_DEVICE=auto` → CUDA se disponível, senão CPU.
- `class_names` extraído do modelo após carregamento.
- Resultado da inferência (`supervision.Detections`) é normalizado para `Detection` interno via `normalize_rfdetr_result`.

### Detection (objeto interno CAMPEX)

```python
@dataclass(frozen=True)
class Detection:
    class_name: str
    confidence: float
    bounding_box: BoundingBox  # (x1, y1, x2, y2)
```

O sistema não expõe objetos específicos do RF-DETR em nenhuma camada além do detector.

## 4. Tracker (ObjectTracker)

### Interface

```python
class ObjectTracker(ABC):
    name: str

    def update(camera_id, detections, timestamp) -> list[TrackedObject]
```

### ByteTrackTracker

- Implementação baseada em IoU (Intersection over Union) para associação de tracks.
- Mantém estado por câmera (cada `VisionSession` tem seu próprio tracker).
- IDs são reaproveitados entre frames enquanto a detecção se sobrepõe.
- Tracks não atualizados por `max_missed` frames são removidos.
- Cada classe é trackada independentemente.

### TrackedObject (objeto interno CAMPEX)

```python
@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    camera_id: str
    class_name: str
    confidence: float
    bounding_box: BoundingBox
    timestamp: datetime
```

## 5. VisionSession

Gerencia o estado de visão para uma única câmera.

### Estados

| Estado      | Significado                                    |
|-------------|------------------------------------------------|
| STOPPED     | Vision não foi iniciada ou foi parada          |
| STARTING    | Sessão criada, aguardando frames               |
| RUNNING     | Frames estão sendo processados                 |
| ERROR       | Falha detectada (camera offline, erro de inferência) |

### Métodos

| Método          | Descrição                                        |
|-----------------|--------------------------------------------------|
| `process()`     | Executa detecção + tracking em um frame          |
| `should_process()`| Rate limiter: respeita `VISION_FPS`            |
| `fail()`        | Marca erro, muda para estado ERROR               |
| `stop()`        | Marca como STOPPED                               |
| `restart()`     | Reseta para STARTING, limpa objetos e estado     |
| `as_status()`   | Retorna status + métricas                        |

### Rate Limiting (VISION_FPS)

- `VISION_FPS=5` → processa 1 frame a cada 200ms.
- Usa `Latest Frame Buffer`: o `CameraWorker` mantém o frame mais recente. O `VisionEngine` pula frames se o detector estiver atrasado.
- Não cria fila de frames — sempre usa o mais recente.

## 6. Camera Offline

- O `VisionEngine` verifica `CameraManager.is_running(camera_id)` em cada ciclo.
- Se a câmera estiver offline: `session.fail("Camera is offline or not running.")` → status ERROR.
- O backend **não cai**. A sessão de visão permanece no motor e automaticamente volta a processar quando a câmera reconecta.
- O modelo RF-DETR **não é recarregado** — permanece na memória.

## 7. Streaming

### MJPEG

```
GET /api/v1/cameras/{camera_id}/stream
Content-Type: multipart/x-mixed-replace; boundary=frame
```

- Cada part é um JPEG codificado via `cv2.imencode`.
- Taxa de envio: ~20 FPS (50ms de intervalo).
- Se não houver frame: imagem em branco com mensagem.
- Se houver objetos tracked: overlay server-side via `draw_tracked_objects()`.

### Overlay

- Bounding boxes desenhados server-side em vermelho/verde.
- Label: `CLASS_NAME #TRACK_ID CONFIDENCE%`
- Futuramente: overlay renderizado no frontend (arquitetura preparada).

## 8. APIs

| Método | Endpoint                                  | Descrição                  |
|--------|-------------------------------------------|----------------------------|
| POST   | `/api/v1/cameras/{id}/vision/start`       | Iniciar Vision             |
| POST   | `/api/v1/cameras/{id}/vision/restart`     | Reiniciar Vision           |
| POST   | `/api/v1/cameras/{id}/vision/stop`        | Parar Vision               |
| GET    | `/api/v1/cameras/{id}/vision/status`      | Status + métricas          |
| GET    | `/api/v1/cameras/{id}/vision/objects`     | Objetos tracked (JSON)     |
| GET    | `/api/v1/cameras/{id}/stream`             | Stream MJPEG               |

### VisionStatus Response

```json
{
  "camera_id": "cam_abc123",
  "status": "RUNNING",
  "error": null,
  "camera_status": "ONLINE",
  "metrics": {
    "camera_fps": 30.0,
    "vision_fps": 5.0,
    "inference_ms": 45.0,
    "objects_detected": 2,
    "device": "CPU",
    "detector": "RF-DETR Nano",
    "tracker": "ByteTrack",
    "uptime": 120.0
  }
}
```

## 9. Configuração

| Variável              | Default | Descrição                              |
|-----------------------|---------|----------------------------------------|
| `VISION_ENABLED`      | `true`  | Habilita/desabilita o motor Vision     |
| `VISION_DETECTOR`     | `rfdetr`| Tipo de detector                       |
| `VISION_DEVICE`       | `auto`  | `auto`, `cpu`, ou `cuda`               |
| `VISION_FPS`          | `5`     | FPS de processamento de visão           |
| `VISION_CONFIDENCE`   | `0.50`  | Threshold mínimo de confiança          |
| `VISION_VIDEO_LOOP`   | `true`  | Loop de arquivos de vídeo (desenvolvimento) |

## 10. Frontend — Página "Ao vivo"

- **Selecionar câmera**: dropdown com câmeras cadastradas.
- **Visualizar vídeo**: `<img>` MJPEG com overlay de bounding boxes.
- **Iniciar Vision**: botão "Vision ON".
- **Parar Vision**: botão "Vision OFF".
- **Reiniciar Vision**: botão "Reiniciar Vision".
- **Live View** mostra:
  - Nome da câmera
  - Status ONLINE/OFFLINE
  - Vision ON/OFF
  - Video stream com bounding boxes
  - Classe, confidence, track ID
  - Camera FPS, Vision FPS, inference time, device
  - Quantidade de objetos

### Auto-atualização

- Status da visão: polling a cada 2 segundos (via `refreshLiveStatus`).
- Stream MJPEG: atualização contínua via `<img>`.

## 11. Testes

### Cobertura (`tests/test_vision_core.py`)

| Teste                                           | Tipo   |
|-------------------------------------------------|--------|
| `test_vision_detector_is_abstract`              | Unit   |
| `test_normalize_rfdetr_result_filters_and_maps_detections` | Unit |
| `test_normalize_rfdetr_result_handles_supervision_detections` | Unit |
| `test_normalize_rfdetr_result_falls_back_to_data_class_name` | Unit |
| `test_normalize_rfdetr_result_resolves_class_from_class_id` | Unit |
| `test_normalize_rfdetr_result_empty_result`   | Unit   |
| `test_normalize_rfdetr_result_handles_missing_confidence` | Unit |
| `test_tracker_keeps_track_id_for_overlapping_detection` | Unit |
| `test_tracker_assigns_new_ids_for_new_objects` | Unit   |
| `test_tracker_different_classes_get_different_ids` | Unit |
| `test_tracker_expired_tracks_are_removed`     | Unit   |
| `test_vision_session_processes_frame_and_tracks_objects` | Unit |
| `test_vision_session_should_process_rate_limits` | Unit |
| `test_vision_session_stop`                      | Unit   |
| `test_vision_session_restart`                   | Unit   |
| `test_vision_session_fail_sets_error`           | Unit   |
| `test_vision_session_status_contains_metrics`  | Unit   |
| `test_vision_engine_disabled_status`            | Unit   |
| `test_vision_session_duplicate_start_reuses_session` | Unit |
| `test_vision_engine_stop_session`               | Unit   |
| `test_vision_engine_restart_session`            | Unit   |
| `test_vision_engine_start_stop_start_without_restart` | Unit |
| `test_vision_engine_camera_offline_sets_error`  | Integration |
| `test_vision_engine_detectors_singleton`        | Unit   |
| `test_vision_engine_error_does_not_crash`       | Integration |
| `test_vision_metrics_has_all_required_fields`   | Unit   |
| `test_tracked_object_as_dict`                   | Unit   |
| `test_detection_as_dict`                        | Unit   |
| `test_create_detector_unsupported_type`         | Unit   |

### Mocks

- `FakeDetector`: implementa `VisionDetector`, retorna detecções fixas.
- `FakeTracker`: implementa `ObjectTracker`, atribui IDs sequenciais.
- `SupervisionLikeDetection`: mock de `supervision.Detections`.

## 12. Performance

- Modelo carregado **uma vez** no startup (lazy load na primeira `start_session`).
- Detector é **singleton** compartilhado entre sessões de câmeras.
- Rate limiting via `VISION_FPS` (padrão 5 FPS).
- `Latest Frame Buffer`: sempre usa o frame mais recente, nunca fila.
- Polling do motor: 20ms (50 FPS) para verificar novos frames.
- Streams MJPEG: ~20 FPS de saída (50ms de intervalo).
- Nenhum acesso a banco de dados por frame.
- Métricas em memória (no `VisionSession`).

## 13. Limitações

- RF-DETR Nano download pesado (~350MB de pesos) na primeira execução.
- Streaming MJPEG não é WebRTC (latência maior).
- Overlay é server-side (futuramente no frontend).
- VideoFileSource loop é para desenvolvimento apenas.
- ByteTrackTracker é uma implementação simplificada (IoU-based), não o algoritmo oficial da FoundationVision.
- Apenas uma câmera ativa no "Ao vivo" (Video Wall futuro).

## 14. Decisões Técnicas

1. **RF-DETR Nano** como detector inicial — escolhido por ser leve, CPU-first, e modular.
2. **ByteTrack custom (IoU)** — o pacote oficial `bytetrack` requer compilação C++ que não é compatível com Windows. Implementação custom mantém a interface `ObjectTracker` para futura substituição.
3. **MJPEG streaming** — solução mais simples e estável para MVP, evoluir para WebRTC no futuro.
4. **Overlay server-side** — reduce complexidade do frontend inicial. Arquitetura preparada para overlay no cliente.
5. **VideoFileSource loop** — permite desenvolvimento e testes sem câmera física.
6. **Threading model**: `CameraWorker` thread separada por câmera + thread único do `VisionEngine`.
