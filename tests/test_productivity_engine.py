from datetime import datetime, timedelta, timezone

from backend.productivity.engine import ProductivityEngine, classify_object
from backend.machines.models import Machine
from backend.vision.models import BoundingBox, TrackedObject
from backend.zones.models import ZonePoint


def _obj(track_id, class_name, box, timestamp):
    return TrackedObject(
        track_id=track_id,
        camera_id="cam_1",
        class_name=class_name,
        confidence=0.9,
        bounding_box=BoundingBox(*box),
        timestamp=timestamp,
    )


def test_classifies_machine_and_phone_classes():
    assert classify_object("person") == "person"
    assert classify_object("forklift") == "machine"
    assert classify_object("cell phone") == "phone"


def test_productivity_flags_idle_person_and_machine_presence():
    engine = ProductivityEngine(idle_seconds=2, still_distance_px=5)
    first = datetime.now(timezone.utc)
    later = first + timedelta(seconds=3)

    engine.analyze("cam_1", [_obj(1, "person", (10, 10, 80, 160), first)], first)
    snapshot = engine.analyze(
        "cam_1",
        [
            _obj(1, "person", (11, 10, 81, 160), later),
            _obj(2, "forklift", (200, 80, 360, 260), later),
        ],
        later,
    )

    assert snapshot["counts"]["people"] == 1
    assert snapshot["counts"]["machines"] == 1
    assert any(signal["type"] == "person_idle" for signal in snapshot["signals"])


def test_productivity_flags_possible_phone_use():
    engine = ProductivityEngine(idle_seconds=60)
    now = datetime.now(timezone.utc)
    snapshot = engine.analyze(
        "cam_1",
        [
            _obj(1, "person", (10, 10, 80, 160), now),
            _obj(2, "cell phone", (50, 50, 70, 80), now),
        ],
        now,
    )

    assert snapshot["counts"]["phones"] == 1
    assert any(signal["type"] == "possible_phone_use" for signal in snapshot["signals"])


def _machine(machine_id="mach_1"):
    return Machine(
        id=machine_id,
        camera_id="cam_1",
        name="Extrusora 01",
        type="fixed",
        enabled=True,
        points=[
            ZonePoint(0.1, 0.1),
            ZonePoint(0.6, 0.1),
            ZonePoint(0.6, 0.6),
            ZonePoint(0.1, 0.6),
        ],
        requires_operator=True,
        allow_idle=False,
        min_person_distance=0.08,
        created_at="2026-09-14T00:00:00+00:00",
        updated_at="2026-09-14T00:00:00+00:00",
    )


def test_machine_state_requires_sustained_activity_before_active():
    engine = ProductivityEngine(machine_active_seconds=2, machine_stopped_seconds=6)
    first = datetime.now(timezone.utc)
    asset = _machine()
    obj = _obj(9, "motorcycle", (20, 20, 40, 40), first)

    first_snapshot = engine.analyze(
        "cam_1",
        [obj],
        first,
        configured_assets=[asset],
        frame_width=100,
        frame_height=100,
    )
    later_snapshot = engine.analyze(
        "cam_1",
        [_obj(9, "motorcycle", (22, 20, 42, 40), first + timedelta(seconds=2.1))],
        first + timedelta(seconds=2.1),
        configured_assets=[asset],
        frame_width=100,
        frame_height=100,
    )

    assert first_snapshot["assets"][0]["state"] == "UNKNOWN"
    assert later_snapshot["assets"][0]["state"] == "ACTIVE"


def test_machine_active_does_not_stop_on_short_visual_gap():
    engine = ProductivityEngine(machine_active_seconds=1, machine_stopped_seconds=5)
    first = datetime.now(timezone.utc)
    asset = _machine()
    engine.analyze("cam_1", [_obj(9, "motorcycle", (20, 20, 40, 40), first)], first, configured_assets=[asset], frame_width=100, frame_height=100)
    active = engine.analyze("cam_1", [_obj(9, "motorcycle", (20, 20, 40, 40), first + timedelta(seconds=1.1))], first + timedelta(seconds=1.1), configured_assets=[asset], frame_width=100, frame_height=100)
    short_gap = engine.analyze("cam_1", [], first + timedelta(seconds=3), configured_assets=[asset], frame_width=100, frame_height=100)

    assert active["assets"][0]["state"] == "ACTIVE"
    assert short_gap["assets"][0]["state"] == "ACTIVE"


def test_camera_offline_makes_machine_unknown_not_stopped():
    engine = ProductivityEngine(machine_active_seconds=1, machine_stopped_seconds=2)
    first = datetime.now(timezone.utc)
    asset = _machine()
    engine.analyze("cam_1", [_obj(9, "motorcycle", (20, 20, 40, 40), first)], first, configured_assets=[asset], frame_width=100, frame_height=100)
    engine.analyze("cam_1", [_obj(9, "motorcycle", (20, 20, 40, 40), first + timedelta(seconds=1.1))], first + timedelta(seconds=1.1), configured_assets=[asset], frame_width=100, frame_height=100)
    offline = engine.analyze(
        "cam_1",
        [],
        first + timedelta(seconds=10),
        camera_status="OFFLINE",
        configured_assets=[asset],
        frame_width=100,
        frame_height=100,
    )

    assert offline["assets"][0]["state"] == "UNKNOWN"


def test_machine_recovers_after_camera_returns_and_evidence_is_sustained():
    engine = ProductivityEngine(machine_active_seconds=1, machine_stopped_seconds=3)
    first = datetime.now(timezone.utc)
    asset = _machine()
    engine.analyze("cam_1", [], first, camera_status="OFFLINE", configured_assets=[asset], frame_width=100, frame_height=100)
    engine.analyze("cam_1", [_obj(9, "motorcycle", (20, 20, 40, 40), first + timedelta(seconds=1))], first + timedelta(seconds=1), configured_assets=[asset], frame_width=100, frame_height=100)
    recovered = engine.analyze("cam_1", [_obj(9, "motorcycle", (20, 20, 40, 40), first + timedelta(seconds=2.1))], first + timedelta(seconds=2.1), configured_assets=[asset], frame_width=100, frame_height=100)

    assert recovered["assets"][0]["state"] == "ACTIVE"
