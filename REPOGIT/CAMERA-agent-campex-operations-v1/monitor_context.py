from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.request import Request, urlopen

import cv2
import numpy as np

from app.config import DATABASE_PATH
from edge_agent.event_sender import enqueue_event, flush_queue

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "context_config.json"
OUTPUT_DIR = ROOT / "output_context"
STOPS_CSV = OUTPUT_DIR / "paradas_contextuais.csv"
TIMELINE_CSV = OUTPUT_DIR / "timeline.csv"
SUMMARY_JSON = OUTPUT_DIR / "resumo_contextual.json"
SNAPSHOT_DIR = OUTPUT_DIR / "snapshots"
DEFAULT_API_URL = os.getenv("API_URL")
DEFAULT_CLIENTE_ID = os.getenv("CLIENTE_ID") or os.getenv("TENANT_ID")
DEFAULT_UNIDADE_ID = os.getenv("UNIDADE_ID") or os.getenv("SITE_ID")
DEFAULT_CAMERA_ID = os.getenv("CAMERA_ID")


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class PersonDetector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Box]: ...


class HogPersonDetector:
    """Detector embutido no OpenCV. Não exige download, mas é apenas para MVP."""

    def __init__(self, confidence_threshold: float = 0.15, process_width: int = 640) -> None:
        self.confidence_threshold = confidence_threshold
        self.process_width = process_width
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame: np.ndarray) -> list[Box]:
        h, w = frame.shape[:2]
        scale = min(1.0, self.process_width / max(1, w))
        small = frame if scale == 1.0 else cv2.resize(
            frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
        )
        rects, weights = self.hog.detectMultiScale(
            small,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        if len(rects) == 0:
            return []

        raw_boxes: list[list[int]] = []
        raw_scores: list[float] = []
        for (x, y, bw, bh), weight in zip(rects, weights):
            score = float(weight)
            if score < self.confidence_threshold:
                continue
            inv = 1.0 / scale
            raw_boxes.append([
                int(x * inv), int(y * inv), int(bw * inv), int(bh * inv)
            ])
            raw_scores.append(score)

        if not raw_boxes:
            return []

        indices = cv2.dnn.NMSBoxes(
            raw_boxes,
            raw_scores,
            score_threshold=self.confidence_threshold,
            nms_threshold=0.35,
        )
        if len(indices) == 0:
            return []

        flattened = np.array(indices).reshape(-1).tolist()
        return [
            Box(*raw_boxes[index], confidence=raw_scores[index])
            for index in flattened
        ]


class YoloPersonDetector:
    """Detector opcional mais forte. Exige `pip install ultralytics`."""

    def __init__(self, model_name: str, confidence_threshold: float) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "Detector YOLO não instalado. Rode: pip install -r requirements-yolo.txt"
            ) from exc
        self.model = YOLO(model_name)
        self.confidence_threshold = confidence_threshold

    def detect(self, frame: np.ndarray) -> list[Box]:
        results = self.model.predict(
            source=frame,
            classes=[0],
            conf=self.confidence_threshold,
            verbose=False,
        )
        boxes: list[Box] = []
        for result in results:
            if result.boxes is None:
                continue
            xyxy = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()
            for coords, confidence in zip(xyxy, confidences):
                x1, y1, x2, y2 = map(int, coords)
                boxes.append(
                    Box(
                        x=x1,
                        y=y1,
                        w=max(1, x2 - x1),
                        h=max(1, y2 - y1),
                        confidence=float(confidence),
                    )
                )
        return boxes


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def time_text(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MVP contextual: máquina rodando/parada + presença automática de pessoa."
    )
    parser.add_argument("--source", required=True, help="MP4, webcam 0 ou URL RTSP")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Refaz a configuração inicial da máquina e da zona do operador.",
    )
    parser.add_argument(
        "--detector",
        choices=["hog", "yolo", "none"],
        default="hog",
        help="Detector de pessoas. HOG funciona sem download; YOLO é opcional.",
    )
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument("--reset-output", action="store_true")
    parser.add_argument("--cliente-id", default=DEFAULT_CLIENTE_ID)
    parser.add_argument("--unidade-id", default=DEFAULT_UNIDADE_ID)
    parser.add_argument("--camera-id", default=DEFAULT_CAMERA_ID)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    return parser.parse_args()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuração não encontrada: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)


def normalize_source(source: str) -> str | int:
    return int(source) if source.strip().isdigit() else source.strip()


def is_live_source(source: str | int) -> bool:
    return isinstance(source, int) or (
        isinstance(source, str)
        and source.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))
    )


def open_capture(source: str | int) -> cv2.VideoCapture:
    if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            "rtsp_transport;tcp|stimeout;5000000",
        )
        capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError("Não foi possível abrir o vídeo, webcam ou RTSP.")
    return capture


def resize_frame(frame: np.ndarray, target_width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= target_width:
        return frame
    scale = target_width / w
    return cv2.resize(
        frame,
        (target_width, int(h * scale)),
        interpolation=cv2.INTER_AREA,
    )


def select_roi(frame: np.ndarray, title: str) -> tuple[int, int, int, int]:
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    x, y, w, h = cv2.selectROI(title, frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    if w <= 0 or h <= 0:
        raise RuntimeError(f"Nenhuma área válida selecionada para: {title}")
    return int(x), int(y), int(w), int(h)


def clamp_roi(
    roi: list[int] | tuple[int, int, int, int], frame: np.ndarray
) -> tuple[int, int, int, int]:
    x, y, w, h = map(int, roi)
    frame_h, frame_w = frame.shape[:2]
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    w = max(1, min(w, frame_w - x))
    h = max(1, min(h, frame_h - y))
    return x, y, w, h


def point_in_roi(point: tuple[int, int], roi: tuple[int, int, int, int]) -> bool:
    px, py = point
    x, y, w, h = roi
    return x <= px <= x + w and y <= py <= y + h


def gray_blur(region: np.ndarray, kernel: int) -> np.ndarray:
    kernel = max(3, kernel)
    if kernel % 2 == 0:
        kernel += 1
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (kernel, kernel), 0)


def motion_score(
    previous: np.ndarray,
    current: np.ndarray,
    pixel_threshold: int,
    morphology_kernel: int,
) -> float:
    difference = cv2.absdiff(previous, current)
    _, mask = cv2.threshold(difference, pixel_threshold, 255, cv2.THRESH_BINARY)
    kernel_size = max(1, morphology_kernel)
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return float(cv2.countNonZero(mask) / max(1, mask.size))


def source_seconds(capture: cv2.VideoCapture, live: bool, wall_start: float) -> float:
    if live:
        return max(0.0, time.monotonic() - wall_start)
    position_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
    if position_ms > 0:
        return position_ms / 1000.0
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    return capture.get(cv2.CAP_PROP_POS_FRAMES) / max(1.0, fps)


def append_csv(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def product_events_enabled(args: argparse.Namespace) -> bool:
    fields = [args.cliente_id, args.unidade_id, args.camera_id, args.api_url]
    if not any(fields):
        return False
    if all(fields):
        return True
    raise RuntimeError(
        "Para registrar eventos automaticamente, informe --cliente-id, "
        "--unidade-id, --camera-id e --api-url."
    )


def post_json(api_url: str, path: str, payload: dict[str, Any], method: str = "POST") -> dict[str, Any]:
    request = Request(
        f"{api_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=5.0) as response:
        body = response.read().decode("utf-8")
        if response.status >= 400:
            raise RuntimeError(f"API retornou HTTP {response.status}")
        return json.loads(body) if body else {}


def send_or_queue(
    api_url: str,
    payload: dict[str, Any],
    method: str = "POST",
    path: str = "/eventos",
) -> dict[str, Any] | None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        try:
            flush_queue(connection, api_url)
        except Exception:
            pass
        try:
            return post_json(api_url, path, payload, method)
        except Exception as exc:
            enqueue_event(connection, payload, method=method, path=path)
            print(f"API indisponível; evento salvo na fila local: {exc}")
            return None


def load_rule_minimum_seconds(camera_id: str | None, fallback: float) -> float:
    if not camera_id or not DATABASE_PATH.exists():
        return fallback
    try:
        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT MAX(tempo_minimo) AS tempo_minimo
                FROM regras
                WHERE camera_id = ? AND ativo = 1
                """,
                (camera_id,),
            ).fetchone()
    except sqlite3.Error:
        return fallback
    if row is None or row["tempo_minimo"] is None:
        return fallback
    return max(fallback, float(row["tempo_minimo"]))


def event_confidence(motion_value: float, motion_threshold: float) -> float:
    if motion_threshold <= 0:
        return 0.0
    distance = max(0.0, motion_threshold - motion_value)
    return round(min(1.0, distance / motion_threshold), 3)


def save_timeline_segment(
    state: str,
    start_iso: str,
    end_iso: str,
    start_seconds: float,
    end_seconds: float,
) -> None:
    duration = max(0.0, end_seconds - start_seconds)
    append_csv(
        TIMELINE_CSV,
        ["estado", "inicio", "fim", "inicio_video_segundos", "fim_video_segundos", "duracao_segundos"],
        {
            "estado": state,
            "inicio": start_iso,
            "fim": end_iso,
            "inicio_video_segundos": round(start_seconds, 3),
            "fim_video_segundos": round(end_seconds, 3),
            "duracao_segundos": round(duration, 3),
        },
    )


def save_stop_event(
    start_iso: str,
    end_iso: str,
    start_seconds: float,
    end_seconds: float,
    operator_present_seconds: float,
    operator_absent_seconds: float,
    maximum_people: int,
    snapshot_path: str,
) -> None:
    duration = max(0.0, end_seconds - start_seconds)
    dominant_context = (
        "PARADA_COM_OPERADOR"
        if operator_present_seconds >= operator_absent_seconds
        else "PARADA_SEM_OPERADOR"
    )
    append_csv(
        STOPS_CSV,
        [
            "inicio",
            "fim",
            "inicio_video_segundos",
            "fim_video_segundos",
            "duracao_segundos",
            "operador_presente_segundos",
            "operador_ausente_segundos",
            "contexto_dominante",
            "maximo_pessoas_detectadas",
            "snapshot",
        ],
        {
            "inicio": start_iso,
            "fim": end_iso,
            "inicio_video_segundos": round(start_seconds, 3),
            "fim_video_segundos": round(end_seconds, 3),
            "duracao_segundos": round(duration, 3),
            "operador_presente_segundos": round(operator_present_seconds, 3),
            "operador_ausente_segundos": round(operator_absent_seconds, 3),
            "contexto_dominante": dominant_context,
            "maximo_pessoas_detectadas": maximum_people,
            "snapshot": snapshot_path,
        },
    )


def write_summary(
    source: str,
    machine_state: str,
    operator_present: bool,
    context_state: str,
    people_count: int,
    stop_count: int,
    total_stopped_seconds: float,
    current_stop_seconds: float,
    motion_value: float,
    motion_threshold: float,
    detector_name: str,
) -> None:
    payload = {
        "updated_at": now_iso(),
        "source": source,
        "machine_state": machine_state,
        "operator_present": operator_present,
        "context_state": context_state,
        "people_count": people_count,
        "stop_count": stop_count,
        "closed_stop_time_seconds": round(total_stopped_seconds, 3),
        "current_stop_time_seconds": round(current_stop_seconds, 3),
        "total_stop_time_seconds": round(total_stopped_seconds + current_stop_seconds, 3),
        "motion_value": round(motion_value, 5),
        "motion_threshold": round(motion_threshold, 5),
        "person_detector": detector_name,
    }
    with SUMMARY_JSON.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def outline_text(
    frame: np.ndarray,
    text: str,
    position: tuple[int, int],
    scale: float = 0.62,
) -> None:
    cv2.putText(
        frame, text, position, cv2.FONT_HERSHEY_SIMPLEX, scale,
        (255, 255, 255), 4, cv2.LINE_AA,
    )
    cv2.putText(
        frame, text, position, cv2.FONT_HERSHEY_SIMPLEX, scale,
        (0, 0, 0), 2, cv2.LINE_AA,
    )


def build_detector(name: str, config: dict[str, Any]) -> PersonDetector | None:
    confidence = float(config.get("person_confidence_threshold", 0.25))
    if name == "none":
        return None
    if name == "yolo":
        return YoloPersonDetector(
            model_name=str(config.get("yolo_model", "yolo11n.pt")),
            confidence_threshold=confidence,
        )
    return HogPersonDetector(
        confidence_threshold=float(config.get("hog_confidence_threshold", 0.15)),
        process_width=int(config.get("person_process_width", 640)),
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    send_product_events = product_events_enabled(args)

    if args.reset_output and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(exist_ok=True)
    SNAPSHOT_DIR.mkdir(exist_ok=True)

    source = normalize_source(args.source)
    live = is_live_source(source)
    capture = open_capture(source)
    ok, raw = capture.read()
    if not ok or raw is None:
        capture.release()
        raise RuntimeError("A fonte abriu, mas não entregou o primeiro quadro.")

    frame = resize_frame(raw, int(config.get("process_width", 960)))
    display = not args.no_display

    machine_roi_saved = config.get("machine_roi")
    operator_zone_saved = config.get("operator_zone")
    setup_needed = args.setup or machine_roi_saved is None or operator_zone_saved is None

    if setup_needed:
        if not display:
            raise RuntimeError("O primeiro setup precisa de janela para selecionar as duas áreas.")
        machine_roi = select_roi(frame, "1 de 2 - Selecione a parte visivel da maquina")
        operator_zone = select_roi(frame, "2 de 2 - Selecione a zona onde o operador trabalha")
        config["machine_roi"] = list(machine_roi)
        config["operator_zone"] = list(operator_zone)
        save_config(config)
    else:
        machine_roi = clamp_roi(machine_roi_saved, frame)
        operator_zone = clamp_roi(operator_zone_saved, frame)

    detector = build_detector(args.detector, config)
    person_detection_interval = max(1, int(config.get("person_detection_interval_frames", 5)))

    mx, my, mw, mh = machine_roi
    previous_machine = gray_blur(
        frame[my : my + mh, mx : mx + mw],
        int(config.get("blur_kernel", 9)),
    )

    motion_threshold = float(config.get("motion_threshold", 0.02))
    confirm_running = float(config.get("confirm_running_seconds", 3.0))
    confirm_stopped = float(config.get("confirm_stopped_seconds", 8.0))
    confirm_operator_present = float(config.get("confirm_operator_present_seconds", 1.0))
    confirm_operator_absent = float(config.get("confirm_operator_absent_seconds", 3.0))
    minimum_event = load_rule_minimum_seconds(
        args.camera_id,
        float(config.get("minimum_event_seconds", 3.0)),
    )

    machine_state = "CALIBRANDO"
    machine_candidate: str | None = None
    machine_candidate_since: float | None = None

    operator_present = False
    operator_candidate: bool | None = None
    operator_candidate_since: float | None = None

    context_state = "CALIBRANDO"
    context_started_seconds = 0.0
    context_started_iso = now_iso()

    stop_start_seconds: float | None = None
    stop_start_iso: str | None = None
    stop_operator_present_seconds = 0.0
    stop_operator_absent_seconds = 0.0
    stop_maximum_people = 0
    stop_snapshot_path = ""
    stop_count = 0
    total_stopped_seconds = 0.0
    product_event_id: str | None = None
    product_event_started = False
    product_event_queued_offline = False

    people_boxes: list[Box] = []
    people_count = 0
    frame_index = 0
    smoothed_motion = 0.0
    wall_start = time.monotonic()
    last_loop_seconds = 0.0
    last_summary_seconds = 0.0
    last_queue_flush_seconds = 0.0
    paused = False

    if display:
        cv2.namedWindow("Visual Operations Context MVP", cv2.WINDOW_NORMAL)

    while True:
        if not paused:
            ok, raw = capture.read()
            if not ok or raw is None:
                break
            frame = resize_frame(raw, int(config.get("process_width", 960)))
            frame_index += 1
            now_seconds = source_seconds(capture, live, wall_start)
            delta_seconds = max(0.0, now_seconds - last_loop_seconds)
            last_loop_seconds = now_seconds

            machine_roi = clamp_roi(machine_roi, frame)
            operator_zone = clamp_roi(operator_zone, frame)
            mx, my, mw, mh = machine_roi
            ox, oy, ow, oh = operator_zone

            current_machine = gray_blur(
                frame[my : my + mh, mx : mx + mw],
                int(config.get("blur_kernel", 9)),
            )
            score = motion_score(
                previous_machine,
                current_machine,
                int(config.get("pixel_difference_threshold", 22)),
                int(config.get("morphology_kernel", 3)),
            )
            previous_machine = current_machine
            smoothed_motion = score if smoothed_motion == 0.0 else 0.25 * score + 0.75 * smoothed_motion
            raw_machine_state = "RODANDO" if smoothed_motion >= motion_threshold else "PARADA"

            if machine_candidate != raw_machine_state:
                machine_candidate = raw_machine_state
                machine_candidate_since = now_seconds
            machine_confirmation = confirm_running if raw_machine_state == "RODANDO" else confirm_stopped
            machine_candidate_duration = (
                now_seconds - machine_candidate_since if machine_candidate_since is not None else 0.0
            )
            if raw_machine_state != machine_state and machine_candidate_duration >= machine_confirmation:
                previous_machine_state = machine_state
                machine_state = raw_machine_state

                if machine_state == "PARADA":
                    stop_start_seconds = machine_candidate_since
                    stop_start_iso = now_iso()
                    stop_operator_present_seconds = 0.0
                    stop_operator_absent_seconds = 0.0
                    stop_maximum_people = people_count
                    product_event_id = None
                    product_event_started = False
                    product_event_queued_offline = False
                    stop_count += 1
                    snapshot = SNAPSHOT_DIR / f"parada_{stop_count:03d}_{datetime.now():%Y%m%d_%H%M%S}.jpg"
                    cv2.imwrite(str(snapshot), frame)
                    stop_snapshot_path = str(snapshot.relative_to(ROOT))

                elif previous_machine_state == "PARADA" and stop_start_seconds is not None:
                    stop_end_seconds = machine_candidate_since or now_seconds
                    duration = max(0.0, stop_end_seconds - stop_start_seconds)
                    if duration >= minimum_event:
                        operator_was_present = stop_operator_present_seconds >= stop_operator_absent_seconds
                        confidence = event_confidence(smoothed_motion, motion_threshold)
                        save_stop_event(
                            start_iso=stop_start_iso or now_iso(),
                            end_iso=now_iso(),
                            start_seconds=stop_start_seconds,
                            end_seconds=stop_end_seconds,
                            operator_present_seconds=stop_operator_present_seconds,
                            operator_absent_seconds=stop_operator_absent_seconds,
                            maximum_people=stop_maximum_people,
                            snapshot_path=stop_snapshot_path,
                        )
                        if send_product_events:
                            close_payload = {
                                "fim": now_iso(),
                                "duracao": round(duration, 3),
                                "operador_presente": operator_was_present,
                                "confianca": confidence,
                                "midia_path": stop_snapshot_path,
                            }
                            if product_event_id:
                                send_or_queue(
                                    args.api_url,
                                    close_payload,
                                    method="PATCH",
                                    path=f"/eventos/{product_event_id}",
                                )
                            else:
                                create_payload = {
                                    "cliente_id": args.cliente_id,
                                    "unidade_id": args.unidade_id,
                                    "camera_id": args.camera_id,
                                    "tipo": "machine_stopped",
                                    "inicio": stop_start_iso or now_iso(),
                                    **close_payload,
                                }
                                send_or_queue(args.api_url, create_payload)
                        total_stopped_seconds += duration
                    stop_start_seconds = None
                    stop_start_iso = None
                    product_event_id = None
                    product_event_started = False
                    product_event_queued_offline = False

            if detector is not None and frame_index % person_detection_interval == 0:
                people_boxes = detector.detect(frame)
                people_count = len(people_boxes)

            raw_operator_present = any(
                point_in_roi(box.center, operator_zone) for box in people_boxes
            )
            if operator_candidate != raw_operator_present:
                operator_candidate = raw_operator_present
                operator_candidate_since = now_seconds
            operator_confirmation = (
                confirm_operator_present if raw_operator_present else confirm_operator_absent
            )
            operator_candidate_duration = (
                now_seconds - operator_candidate_since if operator_candidate_since is not None else 0.0
            )
            if raw_operator_present != operator_present and operator_candidate_duration >= operator_confirmation:
                operator_present = raw_operator_present

            if machine_state == "PARADA" and stop_start_seconds is not None:
                if operator_present:
                    stop_operator_present_seconds += delta_seconds
                else:
                    stop_operator_absent_seconds += delta_seconds
                stop_maximum_people = max(stop_maximum_people, people_count)
                current_stop_duration = max(0.0, now_seconds - stop_start_seconds)
                if send_product_events and not product_event_started and current_stop_duration >= minimum_event:
                    create_payload = {
                        "cliente_id": args.cliente_id,
                        "unidade_id": args.unidade_id,
                        "camera_id": args.camera_id,
                        "tipo": "machine_stopped",
                        "inicio": stop_start_iso or now_iso(),
                        "operador_presente": operator_present,
                        "confianca": event_confidence(smoothed_motion, motion_threshold),
                        "midia_path": stop_snapshot_path,
                    }
                    product_event_started = True
                    try:
                        with sqlite3.connect(DATABASE_PATH) as connection:
                            connection.row_factory = sqlite3.Row
                            flush_queue(connection, args.api_url)
                        response = post_json(args.api_url, "/eventos", create_payload)
                        product_event_id = str(response["id"])
                        print(f"Evento automático aberto: {product_event_id}")
                    except Exception as exc:
                        product_event_queued_offline = True
                        print(f"API indisponível; evento será salvo completo ao fechar a parada: {exc}")

            new_context_state = (
                "CALIBRANDO"
                if machine_state == "CALIBRANDO"
                else f"{machine_state}_{'COM_OPERADOR' if operator_present else 'SEM_OPERADOR'}"
            )
            if new_context_state != context_state:
                if context_state != "CALIBRANDO":
                    save_timeline_segment(
                        context_state,
                        context_started_iso,
                        now_iso(),
                        context_started_seconds,
                        now_seconds,
                    )
                context_state = new_context_state
                context_started_seconds = now_seconds
                context_started_iso = now_iso()

            current_stop_seconds = (
                max(0.0, now_seconds - stop_start_seconds)
                if stop_start_seconds is not None
                else 0.0
            )

            if display:
                annotated = frame.copy()
                machine_color = (
                    (0, 180, 0) if machine_state == "RODANDO"
                    else (0, 0, 220) if machine_state == "PARADA"
                    else (0, 180, 255)
                )
                cv2.rectangle(annotated, (mx, my), (mx + mw, my + mh), machine_color, 3)
                cv2.rectangle(annotated, (ox, oy), (ox + ow, oy + oh), (255, 180, 0), 2)
                cv2.putText(
                    annotated, "ZONA OPERADOR", (ox, max(20, oy - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 180, 0), 2, cv2.LINE_AA,
                )

                for box in people_boxes:
                    person_color = (0, 255, 255) if point_in_roi(box.center, operator_zone) else (255, 0, 255)
                    cv2.rectangle(
                        annotated,
                        (box.x, box.y),
                        (box.x + box.w, box.y + box.h),
                        person_color,
                        2,
                    )
                    cv2.putText(
                        annotated,
                        f"PESSOA {box.confidence:.2f}",
                        (box.x, max(20, box.y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        person_color,
                        1,
                        cv2.LINE_AA,
                    )

                outline_text(annotated, f"CONTEXTO: {context_state}", (20, 35), 0.74)
                outline_text(
                    annotated,
                    f"MAQUINA: {machine_state} | OPERADOR: {'SIM' if operator_present else 'NAO'}",
                    (20, 70),
                )
                outline_text(
                    annotated,
                    f"PESSOAS: {people_count} | MOVIMENTO: {smoothed_motion:.4f} | LIMITE: {motion_threshold:.4f}",
                    (20, 105),
                    0.56,
                )
                outline_text(
                    annotated,
                    f"PARADAS: {stop_count} | TEMPO PARADO: {time_text(total_stopped_seconds + current_stop_seconds)}",
                    (20, 140),
                    0.58,
                )
                outline_text(
                    annotated,
                    "q sair | espaco pausar | r refazer setup | +/- movimento | s foto",
                    (20, annotated.shape[0] - 20),
                    0.48,
                )
                cv2.imshow("Visual Operations Context MVP", annotated)

            if now_seconds - last_summary_seconds >= 2.0:
                write_summary(
                    source=str(args.source),
                    machine_state=machine_state,
                    operator_present=operator_present,
                    context_state=context_state,
                    people_count=people_count,
                    stop_count=stop_count,
                    total_stopped_seconds=total_stopped_seconds,
                    current_stop_seconds=current_stop_seconds,
                    motion_value=smoothed_motion,
                    motion_threshold=motion_threshold,
                    detector_name=args.detector,
                )
                last_summary_seconds = now_seconds

            if send_product_events and now_seconds - last_queue_flush_seconds >= 10.0:
                try:
                    with sqlite3.connect(DATABASE_PATH) as connection:
                        connection.row_factory = sqlite3.Row
                        flush_queue(connection, args.api_url)
                except Exception:
                    pass
                last_queue_flush_seconds = now_seconds

        key = cv2.waitKey(1 if not paused else 30) & 0xFF if display else 255
        if key == ord("q"):
            break
        if key == ord(" "):
            paused = not paused
        if key in (ord("+"), ord("=")):
            motion_threshold += 0.002
            config["motion_threshold"] = round(motion_threshold, 5)
            save_config(config)
        if key in (ord("-"), ord("_")):
            motion_threshold = max(0.001, motion_threshold - 0.002)
            config["motion_threshold"] = round(motion_threshold, 5)
            save_config(config)
        if key == ord("s") and display:
            path = SNAPSHOT_DIR / f"manual_{datetime.now():%Y%m%d_%H%M%S}.jpg"
            cv2.imwrite(str(path), annotated)
            print(f"Imagem salva: {path}")
        if key == ord("r") and display:
            paused = True
            machine_roi = select_roi(frame, "1 de 2 - Selecione a parte visivel da maquina")
            operator_zone = select_roi(frame, "2 de 2 - Selecione a zona onde o operador trabalha")
            config["machine_roi"] = list(machine_roi)
            config["operator_zone"] = list(operator_zone)
            save_config(config)
            mx, my, mw, mh = machine_roi
            previous_machine = gray_blur(
                frame[my : my + mh, mx : mx + mw],
                int(config.get("blur_kernel", 9)),
            )
            paused = False

        if not display and live:
            time.sleep(0.005)

    final_seconds = source_seconds(capture, live, wall_start)

    if context_state != "CALIBRANDO":
        save_timeline_segment(
            context_state,
            context_started_iso,
            now_iso(),
            context_started_seconds,
            final_seconds,
        )

    if stop_start_seconds is not None:
        duration = max(0.0, final_seconds - stop_start_seconds)
        if duration >= minimum_event:
            operator_was_present = stop_operator_present_seconds >= stop_operator_absent_seconds
            confidence = event_confidence(smoothed_motion, motion_threshold)
            save_stop_event(
                start_iso=stop_start_iso or now_iso(),
                end_iso=now_iso(),
                start_seconds=stop_start_seconds,
                end_seconds=final_seconds,
                operator_present_seconds=stop_operator_present_seconds,
                operator_absent_seconds=stop_operator_absent_seconds,
                maximum_people=stop_maximum_people,
                snapshot_path=stop_snapshot_path,
            )
            if send_product_events:
                close_payload = {
                    "fim": now_iso(),
                    "duracao": round(duration, 3),
                    "operador_presente": operator_was_present,
                    "confianca": confidence,
                    "midia_path": stop_snapshot_path,
                }
                if product_event_id:
                    send_or_queue(
                        args.api_url,
                        close_payload,
                        method="PATCH",
                        path=f"/eventos/{product_event_id}",
                    )
                else:
                    create_payload = {
                        "cliente_id": args.cliente_id,
                        "unidade_id": args.unidade_id,
                        "camera_id": args.camera_id,
                        "tipo": "machine_stopped",
                        "inicio": stop_start_iso or now_iso(),
                        **close_payload,
                    }
                    send_or_queue(args.api_url, create_payload)
            total_stopped_seconds += duration

    write_summary(
        source=str(args.source),
        machine_state=machine_state,
        operator_present=operator_present,
        context_state=context_state,
        people_count=people_count,
        stop_count=stop_count,
        total_stopped_seconds=total_stopped_seconds,
        current_stop_seconds=0.0,
        motion_value=smoothed_motion,
        motion_threshold=motion_threshold,
        detector_name=args.detector,
    )

    capture.release()
    cv2.destroyAllWindows()
    print("\nSessão contextual encerrada.")
    print(f"Paradas registradas: {stop_count}")
    print(f"Tempo total parado: {time_text(total_stopped_seconds)}")
    print(f"Paradas: {STOPS_CSV}")
    print(f"Timeline: {TIMELINE_CSV}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
