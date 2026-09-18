from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_DIR = ROOT / "output"
EVENTS_CSV = OUTPUT_DIR / "eventos.csv"
SUMMARY_JSON = OUTPUT_DIR / "resumo.json"
SNAPSHOT_DIR = OUTPUT_DIR / "snapshots"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def time_text(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def open_capture(source: str | int) -> cv2.VideoCapture:
    if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            "rtsp_transport;tcp|stimeout;5000000",
        )
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError("Não foi possível abrir o vídeo, webcam ou RTSP.")
    return cap


def resize_frame(frame: np.ndarray, target_width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= target_width:
        return frame
    scale = target_width / w
    return cv2.resize(frame, (target_width, int(h * scale)), interpolation=cv2.INTER_AREA)


def select_roi(frame: np.ndarray) -> tuple[int, int, int, int]:
    cv2.namedWindow("Selecione a area da maquina", cv2.WINDOW_NORMAL)
    x, y, w, h = cv2.selectROI(
        "Selecione a area da maquina", frame, showCrosshair=True, fromCenter=False
    )
    cv2.destroyWindow("Selecione a area da maquina")
    if w <= 0 or h <= 0:
        raise RuntimeError("Nenhuma área válida foi selecionada.")
    return int(x), int(y), int(w), int(h)


def clamp_roi(roi: list[int] | tuple[int, int, int, int], frame: np.ndarray) -> tuple[int, int, int, int]:
    x, y, w, h = map(int, roi)
    fh, fw = frame.shape[:2]
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(1, min(w, fw - x))
    h = max(1, min(h, fh - y))
    return x, y, w, h


def gray_blur(region: np.ndarray, kernel: int) -> np.ndarray:
    kernel = max(3, kernel)
    if kernel % 2 == 0:
        kernel += 1
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (kernel, kernel), 0)


def motion_score(prev: np.ndarray, current: np.ndarray, pixel_threshold: int, morph: int) -> float:
    diff = cv2.absdiff(prev, current)
    _, mask = cv2.threshold(diff, pixel_threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((max(1, morph), max(1, morph)), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return float(cv2.countNonZero(mask) / max(1, mask.size))


def source_seconds(cap: cv2.VideoCapture, live: bool, wall_start: float) -> float:
    if live:
        return max(0.0, time.monotonic() - wall_start)
    pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
    if pos_ms > 0:
        return pos_ms / 1000.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    return cap.get(cv2.CAP_PROP_POS_FRAMES) / max(1.0, fps)


def save_event(start_iso: str, end_iso: str, start_s: float, end_s: float) -> None:
    new_file = not EVENTS_CSV.exists()
    with EVENTS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["inicio", "fim", "inicio_video_segundos", "fim_video_segundos", "duracao_segundos"],
        )
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "inicio": start_iso,
                "fim": end_iso,
                "inicio_video_segundos": round(start_s, 3),
                "fim_video_segundos": round(end_s, 3),
                "duracao_segundos": round(max(0.0, end_s - start_s), 3),
            }
        )


def write_summary(source: str, state: str, count: int, closed_stop: float, current_stop: float, threshold: float) -> None:
    payload = {
        "updated_at": now_iso(),
        "source": source,
        "state": state,
        "stop_count": count,
        "closed_stop_time_seconds": round(closed_stop, 3),
        "current_stop_time_seconds": round(current_stop, 3),
        "total_stop_time_seconds": round(closed_stop + current_stop, 3),
        "motion_threshold": round(threshold, 5),
    }
    with SUMMARY_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def outline_text(frame: np.ndarray, text: str, pos: tuple[int, int], scale: float = 0.65) -> None:
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 2, cv2.LINE_AA)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mede máquina rodando/parada por movimento visual.")
    parser.add_argument("--source", required=True, help="MP4, webcam 0 ou URL RTSP")
    parser.add_argument("--reset-roi", action="store_true")
    args = parser.parse_args()

    config = load_config()
    source: str | int = int(args.source) if args.source.isdigit() else args.source
    live = isinstance(source, int) or (isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")))

    OUTPUT_DIR.mkdir(exist_ok=True)
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    cap = open_capture(source)
    ok, raw = cap.read()
    if not ok or raw is None:
        raise RuntimeError("A fonte abriu, mas não entregou o primeiro quadro.")

    frame = resize_frame(raw, int(config["process_width"]))
    roi_saved = None if args.reset_roi else config.get("roi")
    roi = select_roi(frame) if roi_saved is None else clamp_roi(roi_saved, frame)
    config["roi"] = list(roi)
    save_config(config)

    x, y, w, h = roi
    previous = gray_blur(frame[y:y+h, x:x+w], int(config["blur_kernel"]))

    threshold = float(config["motion_threshold"])
    confirm_running = float(config["confirm_running_seconds"])
    confirm_stopped = float(config["confirm_stopped_seconds"])
    minimum_event = float(config["minimum_event_seconds"])

    stable_state = "CALIBRANDO"
    candidate_state: str | None = None
    candidate_since: float | None = None
    stop_start_s: float | None = None
    stop_start_iso: str | None = None
    stop_count = 0
    total_stopped = 0.0
    smoothed_motion = 0.0
    wall_start = time.monotonic()
    paused = False
    last_summary = 0.0

    cv2.namedWindow("Visual Operations MVP", cv2.WINDOW_NORMAL)

    while True:
        if not paused:
            ok, raw = cap.read()
            if not ok or raw is None:
                break
            frame = resize_frame(raw, int(config["process_width"]))
            x, y, w, h = clamp_roi(roi, frame)
            current = gray_blur(frame[y:y+h, x:x+w], int(config["blur_kernel"]))
            score = motion_score(
                previous,
                current,
                int(config["pixel_difference_threshold"]),
                int(config["morphology_kernel"]),
            )
            previous = current
            smoothed_motion = score if smoothed_motion == 0 else 0.25 * score + 0.75 * smoothed_motion
            now_s = source_seconds(cap, live, wall_start)
            raw_state = "RODANDO" if smoothed_motion >= threshold else "PARADA"

            if candidate_state != raw_state:
                candidate_state = raw_state
                candidate_since = now_s

            needed = confirm_running if raw_state == "RODANDO" else confirm_stopped
            candidate_duration = now_s - candidate_since if candidate_since is not None else 0.0

            if raw_state != stable_state and candidate_duration >= needed:
                stable_state = raw_state
                if stable_state == "PARADA":
                    stop_start_s = candidate_since
                    stop_start_iso = now_iso()
                    stop_count += 1
                elif stable_state == "RODANDO" and stop_start_s is not None:
                    end_s = candidate_since or now_s
                    duration = max(0.0, end_s - stop_start_s)
                    if duration >= minimum_event:
                        save_event(stop_start_iso or now_iso(), now_iso(), stop_start_s, end_s)
                        total_stopped += duration
                    stop_start_s = None
                    stop_start_iso = None

            current_stop = max(0.0, now_s - stop_start_s) if stop_start_s is not None else 0.0
            annotated = frame.copy()
            color = (0, 180, 0) if stable_state == "RODANDO" else (0, 0, 220) if stable_state == "PARADA" else (0, 180, 255)
            cv2.rectangle(annotated, (x, y), (x+w, y+h), color, 3)
            outline_text(annotated, f"ESTADO: {stable_state}", (20, 35), 0.85)
            outline_text(annotated, f"MOVIMENTO: {smoothed_motion:.4f} | LIMITE: {threshold:.4f}", (20, 70))
            outline_text(annotated, f"PARADAS: {stop_count} | TEMPO PARADO: {time_text(total_stopped + current_stop)}", (20, 105))
            outline_text(annotated, "q sair | espaco pausar | r nova area | +/- ajustar | s foto", (20, annotated.shape[0]-20), 0.52)
            cv2.imshow("Visual Operations MVP", annotated)

            if now_s - last_summary >= 2.0:
                write_summary(str(args.source), stable_state, stop_count, total_stopped, current_stop, threshold)
                last_summary = now_s

        key = cv2.waitKey(1 if not paused else 30) & 0xFF
        if key == ord("q"):
            break
        if key == ord(" "):
            paused = not paused
        if key in (ord("+"), ord("=")):
            threshold += 0.002
            config["motion_threshold"] = round(threshold, 5)
            save_config(config)
        if key in (ord("-"), ord("_")):
            threshold = max(0.001, threshold - 0.002)
            config["motion_threshold"] = round(threshold, 5)
            save_config(config)
        if key == ord("s"):
            path = SNAPSHOT_DIR / f"snapshot_{datetime.now():%Y%m%d_%H%M%S}.jpg"
            cv2.imwrite(str(path), annotated)
            print(f"Imagem salva: {path}")
        if key == ord("r"):
            paused = True
            roi = select_roi(frame)
            config["roi"] = list(roi)
            save_config(config)
            x, y, w, h = roi
            previous = gray_blur(frame[y:y+h, x:x+w], int(config["blur_kernel"]))
            paused = False

    final_s = source_seconds(cap, live, wall_start)
    if stop_start_s is not None:
        duration = max(0.0, final_s - stop_start_s)
        if duration >= minimum_event:
            save_event(stop_start_iso or now_iso(), now_iso(), stop_start_s, final_s)
            total_stopped += duration

    write_summary(str(args.source), stable_state, stop_count, total_stopped, 0.0, threshold)
    cap.release()
    cv2.destroyAllWindows()
    print(f"Paradas: {stop_count}")
    print(f"Tempo total parado: {time_text(total_stopped)}")
    print(f"Eventos: {EVENTS_CSV}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
