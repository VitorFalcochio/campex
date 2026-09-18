from __future__ import annotations

import argparse
import os
import sys
import time

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa vídeo, webcam ou stream RTSP.")
    parser.add_argument("--source", required=True)
    args = parser.parse_args()

    source: str | int = int(args.source) if args.source.isdigit() else args.source

    if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            "rtsp_transport;tcp|stimeout;5000000",
        )
        capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        capture = cv2.VideoCapture(source)

    if not capture.isOpened():
        print("ERRO: não foi possível abrir a fonte.", file=sys.stderr)
        return 1

    started = time.monotonic()
    frames = 0
    cv2.namedWindow("Teste da fonte", cv2.WINDOW_NORMAL)

    while True:
        ok, frame = capture.read()
        if not ok or frame is None:
            print("A fonte parou de entregar quadros.", file=sys.stderr)
            break

        frames += 1
        elapsed = max(0.001, time.monotonic() - started)
        fps = frames / elapsed
        cv2.putText(
            frame,
            f"Fonte OK | FPS: {fps:.1f} | q para sair",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Teste da fonte", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    capture.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
