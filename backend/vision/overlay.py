from __future__ import annotations

from typing import Any

import cv2

from backend.vision.models import PoseEstimate, TrackedObject


class OverlayRenderer:
    box_color = (0, 255, 128)
    pose_color = (255, 180, 0)
    joint_color = (0, 220, 255)
    label_background = (0, 0, 0)
    label_color = (255, 255, 255)
    skeleton_edges = (
        ("left_shoulder", "right_shoulder"),
        ("left_shoulder", "left_elbow"),
        ("left_elbow", "left_wrist"),
        ("right_shoulder", "right_elbow"),
        ("right_elbow", "right_wrist"),
        ("left_shoulder", "left_hip"),
        ("right_shoulder", "right_hip"),
        ("left_hip", "right_hip"),
        ("left_hip", "left_knee"),
        ("left_knee", "left_ankle"),
        ("right_hip", "right_knee"),
        ("right_knee", "right_ankle"),
        ("nose", "left_eye"),
        ("nose", "right_eye"),
        ("left_eye", "left_ear"),
        ("right_eye", "right_ear"),
    )

    def render(
        self,
        frame: Any,
        objects: list[TrackedObject],
        poses: list[PoseEstimate] | None = None,
    ) -> Any:
        output = frame.copy()
        for tracked in objects:
            self._draw_tracked_object(output, tracked)
        for pose in poses or []:
            self._draw_pose(output, pose)
        return output

    def _draw_tracked_object(self, frame: Any, tracked: TrackedObject) -> None:
        box = tracked.bounding_box
        x1, y1, x2, y2 = [int(value) for value in box.as_list()]
        label = f"{tracked.class_name.upper()} #{tracked.track_id} {tracked.confidence:.0%}"
        label_width = max(140, min(260, 10 + len(label) * 10))
        cv2.rectangle(frame, (x1, y1), (x2, y2), self.box_color, 2)
        cv2.rectangle(
            frame,
            (x1, max(0, y1 - 24)),
            (x1 + label_width, y1),
            self.label_background,
            -1,
        )
        cv2.putText(
            frame,
            label,
            (x1 + 6, max(16, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            self.label_color,
            1,
            cv2.LINE_AA,
        )

    def _draw_pose(self, frame: Any, pose: PoseEstimate) -> None:
        points = {keypoint.name: keypoint for keypoint in pose.keypoints}
        for first_name, second_name in self.skeleton_edges:
            first = points.get(first_name)
            second = points.get(second_name)
            if first is None or second is None:
                continue
            cv2.line(
                frame,
                (int(first.x), int(first.y)),
                (int(second.x), int(second.y)),
                self.pose_color,
                2,
                cv2.LINE_AA,
            )
        for keypoint in pose.keypoints:
            cv2.circle(
                frame,
                (int(keypoint.x), int(keypoint.y)),
                4,
                self.joint_color,
                -1,
                cv2.LINE_AA,
            )


def draw_tracked_objects(frame: Any, objects: list[TrackedObject]) -> Any:
    return OverlayRenderer().render(frame, objects)
