from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.config import API_PORT, DATABASE_PATH
from app.edge_pilot_check import format_edge_pilot_check, run_edge_pilot_check

from deployment.doctor import READY, format_doctor, run_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Campex Pilot Preflight RC1.")
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH") or str(DATABASE_PATH))
    parser.add_argument("--api-url", default=os.getenv("CAMPEX_API_URL") or f"http://127.0.0.1:{API_PORT}")
    parser.add_argument("--camera-timeout", type=float, default=5.0)
    parser.add_argument("--http-timeout", type=float, default=3.0)
    parser.add_argument("--min-free-gb", type=float, default=5.0)
    parser.add_argument(
        "--profile",
        choices=("local", "external"),
        default="local",
        help="local tolera Cloud ausente; external exige Cloud e sincronização operacional.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    doctor = run_doctor(
        db_path=Path(args.db),
        api_url=args.api_url,
        timeout=args.http_timeout,
        min_free_gb=args.min_free_gb,
        cloud_required=args.profile == "external",
    )
    pilot = run_edge_pilot_check(
        db_path=Path(args.db),
        api_url=args.api_url,
        camera_timeout=args.camera_timeout,
        http_timeout=args.http_timeout,
    )
    print("CAMPEX PILOT PREFLIGHT")
    print(f"PROFILE: {args.profile.upper()}")
    print()
    print(format_doctor(doctor))
    print()
    print(format_edge_pilot_check(pilot))
    ready = doctor.result == READY and pilot.result in {"READY FOR PILOT", "READY WITH ATTENTION"}
    print()
    print("RESULT: READY TO LEAVE RUNNING" if ready else "RESULT: NOT READY TO LEAVE RUNNING")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
