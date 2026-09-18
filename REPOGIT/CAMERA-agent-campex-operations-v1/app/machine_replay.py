from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2

from app.machine_monitoring import MachineMonitorEngine, config_from_dict
from app.person_detection import PersonAnalysisEngine


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def state_at(segments: list[dict[str, Any]], second: float) -> str | None:
    for segment in segments:
        if float(segment["start"]) <= second < float(segment["end"]):
            return segment.get("machine_state")
    return None


def evaluate_state_samples(expected: list[dict[str, Any]], detected: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    correct = 0
    unknown = 0
    transitions = 0
    missed_transitions = 0
    previous_expected = None
    previous_detected = None
    for sample in detected:
        second = float(sample["second"])
        expected_state = state_at(expected, second)
        detected_state = sample.get("machine_state")
        if expected_state is None:
            continue
        total += 1
        if detected_state == "UNKNOWN":
            unknown += 1
        if expected_state == detected_state:
            correct += 1
        if previous_expected and expected_state != previous_expected:
            transitions += 1
            if previous_detected == detected_state:
                missed_transitions += 1
        previous_expected = expected_state
        previous_detected = detected_state
    confidences = [float(sample.get("confidence") or 0) for sample in detected]
    return {
        "samples": total,
        "tempo_correto_percentual": round((correct / total) * 100, 2) if total else 0,
        "amostras_unknown": unknown,
        "transicoes_anotadas": transitions,
        "transicoes_perdidas": missed_transitions,
        "confianca_media": round(sum(confidences) / len(confidences), 3) if confidences else 0,
    }


def run_machine_replay(video_path: str | Path, config_path: str | Path, annotations_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    config = config_from_dict(load_json(config_path))
    annotations = load_json(annotations_path)
    engine = MachineMonitorEngine(config)
    detector = PersonAnalysisEngine()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Nao foi possivel abrir o video de replay.")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    detected: list[dict[str, Any]] = []
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        second = frame_index / max(fps, 1.0)
        frame_index += 1
        if frame_index % max(1, int(fps // max(engine.analysis_fps, 1.0))) != 0:
            continue
        detections = detector.analyze(frame)
        state = engine.update(frame, detections)
        detected.append(
            {
                "second": round(second, 3),
                "machine_state": state.state,
                "operator_present": state.operator_present,
                "confidence": state.confidence,
                "activity_score": state.smoothed_motion,
            }
        )
    capture.release()
    report = {
        "video": str(video_path),
        "machine_id": config.id,
        "machine_name": config.nome,
        "annotations": annotations,
        "detected_samples": detected,
        "metrics": evaluate_state_samples(annotations, detected),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
