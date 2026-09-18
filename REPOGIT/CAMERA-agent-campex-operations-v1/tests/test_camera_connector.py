from __future__ import annotations

import unittest

import numpy as np

from edge_agent.camera_connector import CameraSource, SourceType, UniversalCameraConnector, detect_source_type, safe_source_ref
from edge_agent.onvif_discovery import parse_probe_response


class FakeCapture:
    def __init__(self, frames: list[object], opened: bool = True) -> None:
        self.frames = frames
        self.opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def read(self) -> tuple[bool, object | None]:
        if not self.frames:
            self.opened = False
            return False, None
        return True, self.frames.pop(0)

    def get(self, prop: int) -> float:
        return 10.0

    def release(self) -> None:
        self.released = True


class CameraConnectorTest(unittest.TestCase):
    def test_source_detection_and_secret_masking(self) -> None:
        self.assertEqual(detect_source_type("video.mp4"), SourceType.FILE)
        self.assertEqual(detect_source_type("0"), SourceType.WEBCAM)
        self.assertEqual(detect_source_type("rtsp://user:pass@10.0.0.5/live"), SourceType.RTSP)
        self.assertEqual(
            safe_source_ref("rtsp://user:pass@10.0.0.5:554/live"),
            "rtsp://***:***@10.0.0.5:554/live",
        )

    def test_reconnect_after_stream_drop(self) -> None:
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        captures = [FakeCapture([]), FakeCapture([frame])]

        def factory(_source: object) -> FakeCapture:
            return captures.pop(0)

        connector = UniversalCameraConnector(
            CameraSource(camera_id="cam_1", source="fake.mp4", reconnect_seconds=0),
            capture_factory=factory,
        )
        received = next(connector.frames())
        connector.stop()
        self.assertEqual(received.shape[:2], (20, 30))
        self.assertEqual(connector.info.status, "online")

    def test_two_cameras_are_independent(self) -> None:
        frame_a = np.zeros((10, 10, 3), dtype=np.uint8)
        frame_b = np.zeros((15, 15, 3), dtype=np.uint8)
        camera_a = UniversalCameraConnector(
            CameraSource(camera_id="a", source="a.mp4"),
            capture_factory=lambda _source: FakeCapture([frame_a]),
        )
        camera_b = UniversalCameraConnector(
            CameraSource(camera_id="b", source="b.mp4"),
            capture_factory=lambda _source: FakeCapture([frame_b]),
        )
        self.assertEqual(next(camera_a.frames()).shape[:2], (10, 10))
        self.assertEqual(next(camera_b.frames()).shape[:2], (15, 15))
        camera_a.stop()
        camera_b.stop()

    def test_onvif_probe_response_parser(self) -> None:
        xml = """
        <e:Envelope>
          <e:Body>
            <d:ProbeMatches>
              <d:ProbeMatch>
                <d:Types>dn:NetworkVideoTransmitter</d:Types>
                <d:Scopes>onvif://www.onvif.org/name/TestCamera</d:Scopes>
                <d:XAddrs>http://192.168.1.20/onvif/device_service</d:XAddrs>
              </d:ProbeMatch>
            </d:ProbeMatches>
          </e:Body>
        </e:Envelope>
        """
        devices = parse_probe_response(xml)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].xaddr, "http://192.168.1.20/onvif/device_service")


if __name__ == "__main__":
    unittest.main()
