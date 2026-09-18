# CAMPEX — Agent Handoff

CURRENT STATE
=============
Sprint 2 — Vision Core V1 (PASS WITH FIXES after ByteTrack review)

The full vision pipeline is implemented and tested (60 tests passing):

  CameraSource → LatestFrameBuffer → VisionEngine._run() (scheduler)
  → MotionDetector (pre-trigger) → RFDETRDetector → ByteTrackAdapter
  → OverlayRenderer → MJPEG Stream → Frontend Live View

Key components:
- backend/cameras/      — CameraSource abstraction, Webcam/VideoFile/RTSP sources, CameraManager, LatestFrameBuffer
- backend/vision/       — VisionDetector (RFDETRDetector), ObjectTracker (ByteTrackTracker), MotionDetector, VisionSession, VisionEngine, OverlayRenderer
- backend/api/vision.py — REST endpoints (start/restart/stop/status/objects) + async MJPEG stream with client-disconnect detection
- frontend/             — "Ao vivo" page with Vision ON/OFF toggle, MJPEG stream, tracking overlay, metrics dashboard

Session lifecycle states: STARTING, STOPPED, RUNNING, ERROR, RECOVER
- RECOVER: transient state when a session in ERROR successfully begins processing again (e.g., camera reconnected)

Detector is a singleton loaded once per runtime. CUDA auto-detected, CPU fallback.
Tracker IDs are local per-camera (each VisionSession owns its ByteTrackAdapter/ObjectTracker).
MotionDetector acts as a low-cost pre-trigger — skips RF-DETR inference when no motion (with periodic full-scan every 30 frames).

Configuration: .env / environment variables (VISION_ENABLED, VISION_DETECTOR, VISION_DEVICE, VISION_FPS, VISION_CONFIDENCE, VISION_VIDEO_LOOP)
Backend binds to 0.0.0.0:8000 (start.bat), CORS allows all origins by default for LAN support.
Frontend API_BASE_URL derives from window.location.hostname for LAN support.

LAST COMPLETED TASK
===================
Sprint 2 ByteTrack review/validation:
- Found import-time failure: `backend.vision.tracker` required `supervision` and `trackers` at module import, but the current environment did not have them installed, causing Vision tests/backend import to fail.
- Added `supervision==0.30.2` and `trackers==2.6.0` to `requirements.txt` for the external ByteTrack adapter path.
- Made `ByteTrackAdapter` import external packages lazily and fall back to the local IoU tracker when dependencies are unavailable, preserving backend availability.
- Aligned fallback behavior with the adapter contract: new tracks require consecutive confirmation before being emitted, then keep stable IDs across movement.
- Fixed `VisionSession.restart()` so tracker state is reset when Vision restarts; stale track state no longer leaks across restart.
- Replaced silent overlay failure swallowing with logged exception context in MJPEG streaming.
- Added tracking acceptance tests for moving object stability, two people, short missed detection, object expiration/new track, two-camera isolation, empty detections, reset, and failure isolation.
- Validation executed: `python -m pytest tests\test_vision_core.py --maxfail=1 -vv` → 46 passed; `python -m pytest --maxfail=1 -vv` → 60 passed; `python -m compileall backend scripts tests` → passed.

IMPORTANT DECISIONS
===================
1. `ByteTrackAdapter` is the production tracker used by `VisionSession`. It uses the external `trackers.ByteTrackTracker` package when installed; if `supervision`/`trackers` are unavailable, it falls back to the local IoU tracker so Vision imports and tests do not crash.
2. Overlay is server-side (drawn on JPEG in MJPEG stream), not client-side. Architecture is prepared for frontend overlay in future sprint.
3. VideoFileSource loop mode is for development/testing only (VISION_VIDEO_LOOP=true).
4. LatestFrameBuffer is a single-slot buffer — new frames replace stale, no queues. Prevents latency accumulation.
5. MotionDetector is optional optimization — always runs detection on first frame per session, then skips when no motion.
6. Track IDs are local to each camera (per-session tracker). No cross-camera identity. This is intentional for Sprint 2.

KNOWN ISSUES
=============
- RF-DETR Nano model download (~350MB) required on first inference. Real RF-DETR inference was not validated in this review environment (mocked via FakeDetector).
- MJPEG streaming is not WebRTC — higher latency than WebRTC would provide.
- RTSP source not validated with a real camera — needs physical testing.
- Overlay is burned server-side into JPEG; future sprint should render overlay in frontend via JSON track data.
- Attempted live `pip install supervision trackers`, but it stalled during install and was interrupted. Current automated validation used the fallback IoU tracker path; a fresh environment should install `requirements.txt` to validate the external adapter path.
- Real video validation with RF-DETR + external ByteTrack was not performed in this pass because detector/model/dependencies were not available.

NEXT RECOMMENDED TASK
=====================
Sprint 3 — Detection confidence tuning & deterministic video tests
- Add per-class confidence thresholds (VISION_PERSON_CONFIDENCE)
- Add recorded-video regression test with a known fixture file
- Add WebSocket for realtime track updates (currently 2s polling)
- Optimize RF-DETR inference for CPU (torch.compile, batch inference)
- Migrate ByteTrackTracker to official bytetrack when Linux environment available
