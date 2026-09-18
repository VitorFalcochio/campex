from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("campex.vision.motion")


@dataclass(frozen=True)
class MotionResult:
    motion_detected: bool
    motion_pixels: int
    motion_ratio: float
    regions: list[tuple[int, int, int, int]] = field(default_factory=list)
    # V2 additions (backward-compatible optional fields):
    motion_center: tuple[float, float] | None = None  # (cx, cy) in original frame coords
    motion_magnitude: float = 0.0  # average motion intensity (0–255)
    motion_direction: tuple[float, float] | None = None  # velocity vector (dx, dy) pixels/frame
    global_change_detected: bool = False


class MotionDetector:
    """Lightweight OpenCV-based motion detector (V1).

    Uses grayscale conversion, Gaussian blur, and frame differencing
    to detect scene changes at low computational cost.  This serves as
    a cheap pre-trigger for the Vision scheduler — full object detection
    is skipped when no motion is present, conserving CPU/GPU.
    """

    def __init__(
        self,
        resize_width: int = 64,
        blur_size: int = 3,
        motion_threshold: float = 0.015,
        minimum_motion_pixels: int = 50,
    ) -> None:
        self._resize_width = resize_width
        self._blur_size = blur_size
        self._motion_threshold = motion_threshold
        self._minimum_motion_pixels = minimum_motion_pixels
        self._previous_frame: np.ndarray | None = None

    def detect(self, frame: Any) -> MotionResult:
        small = self._preprocess(frame)
        if small is None:
            return MotionResult(False, 0, 0.0)

        if self._previous_frame is None:
            self._previous_frame = small
            return MotionResult(False, 0, 0.0)

        diff = cv2.absdiff(small, self._previous_frame)
        self._previous_frame = small
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_pixels = int(cv2.countNonZero(thresh))
        total_pixels = thresh.shape[0] * thresh.shape[1]
        ratio = motion_pixels / total_pixels if total_pixels else 0.0

        motion_detected = (
            ratio >= self._motion_threshold
            and motion_pixels >= self._minimum_motion_pixels
        )

        regions = self._extract_regions(thresh) if motion_detected else []

        if motion_detected:
            logger.debug(
                "Motion detected",
                extra={"motion_pixels": motion_pixels, "motion_ratio": round(ratio, 4)},
            )

        return MotionResult(motion_detected, motion_pixels, ratio, regions)

    @property
    def has_reference(self) -> bool:
        return self._previous_frame is not None

    def reset(self) -> None:
        self._previous_frame = None

    def _preprocess(self, frame: Any) -> np.ndarray | None:
        if frame is None:
            return None
        try:
            height = frame.shape[0]
            aspect = self._resize_width / max(1, frame.shape[1])
            new_height = max(1, int(height * aspect))
            resized = cv2.resize(frame, (self._resize_width, new_height))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            return cv2.GaussianBlur(gray, (self._blur_size, self._blur_size), 0)
        except Exception:
            return None

    @staticmethod
    def _extract_regions(thresh: np.ndarray) -> list[tuple[int, int, int, int]]:
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions: list[tuple[int, int, int, int]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 50:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            regions.append((int(x), int(y), int(x + w), int(y + h)))
        return regions


class MotionEngine:
    """Motion Engine V2 — MOG2 background subtraction with motion quality metrics.

    Replaces simple frame differencing with OpenCV's MOG2 background subtractor,
    which is more robust to gradual lighting changes and camera noise.  Also
    tracks motion centroid / direction across frames to provide quality signals
    that downstream engines (Spatial, Event) can use to filter weak detections.

    Lifecycle:
    - First ``detect()`` call initializes the background model — returns no motion.
    - Subsequent calls compare against the learned background and return full
      ``MotionResult`` with centroid, magnitude, and direction.
    """

    def __init__(
        self,
        resize_width: int = 96,
        motion_threshold: float = 0.01,
        minimum_motion_pixels: int = 50,
        min_area: int = 100,
        morph_kernel_size: int = 3,
        history: int = 500,
        var_threshold: float = 16.0,
        global_change_threshold: float = 0.65,
    ) -> None:
        self._resize_width = resize_width
        self._motion_threshold = motion_threshold
        self._minimum_motion_pixels = minimum_motion_pixels
        self._min_area = min_area
        self._morph_kernel_size = morph_kernel_size
        self._history = history
        self._var_threshold = var_threshold
        self._global_change_threshold = global_change_threshold
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history,
            varThreshold=var_threshold,
            detectShadows=False,
        )
        self._bg_initialized = False
        self._prev_centroid: tuple[float, float] | None = None
        self._scale_x: float = 1.0
        self._scale_y: float = 1.0

    def detect(self, frame: Any) -> MotionResult:
        small = self._preprocess(frame)
        if small is None:
            return MotionResult(False, 0, 0.0)

        # First frame initializes the MOG2 background model — skip reporting.
        if not self._bg_initialized:
            self._bg_subtractor.apply(small)
            self._bg_initialized = True
            return MotionResult(False, 0, 0.0)

        fg_mask = self._bg_subtractor.apply(small)
        _, thresh = cv2.threshold(fg_mask, 127, 255, cv2.THRESH_BINARY)
        thresh = self._clean_mask(thresh)

        motion_pixels = int(cv2.countNonZero(thresh))
        total_pixels = thresh.shape[0] * thresh.shape[1]
        ratio = motion_pixels / total_pixels if total_pixels else 0.0
        motion_magnitude = (
            float(thresh.sum()) / max(1, motion_pixels) if motion_pixels else 0.0
        )

        global_change_detected = ratio >= self._global_change_threshold
        motion_detected = (
            not global_change_detected
            and
            ratio >= self._motion_threshold
            and motion_pixels >= self._minimum_motion_pixels
        )

        regions = self._extract_regions(thresh) if motion_detected else []

        # Compute centroid of motion in small-frame coords, then scale to original frame
        motion_center: tuple[float, float] | None = None
        motion_direction: tuple[float, float] | None = None

        if motion_detected and motion_pixels > 0:
            ys, xs = np.where(thresh > 0)
            if len(xs) > 0:
                cx_small = float(xs.mean())
                cy_small = float(ys.mean())
                motion_center = (
                    cx_small * self._scale_x,
                    cy_small * self._scale_y,
                )

                if self._prev_centroid is not None:
                    motion_direction = (
                        motion_center[0] - self._prev_centroid[0],
                        motion_center[1] - self._prev_centroid[1],
                    )

        if motion_detected:
            logger.debug(
                "Motion detected (V2)",
                extra={
                    "motion_pixels": motion_pixels,
                    "motion_ratio": round(ratio, 4),
                    "motion_direction": (
                        round(motion_direction[0], 2),
                        round(motion_direction[1], 2),
                    )
                    if motion_direction
                    else None,
                },
            )

        if motion_center is not None:
            self._prev_centroid = motion_center

        return MotionResult(
            motion_detected=motion_detected,
            motion_pixels=motion_pixels,
            motion_ratio=ratio,
            regions=regions,
            motion_center=motion_center,
            motion_magnitude=motion_magnitude,
            motion_direction=motion_direction,
            global_change_detected=global_change_detected,
        )

    @property
    def has_reference(self) -> bool:
        return self._bg_initialized

    def reset(self) -> None:
        self._bg_initialized = False
        self._prev_centroid = None
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=self._history,
            varThreshold=self._var_threshold,
            detectShadows=False,
        )

    def _preprocess(self, frame: Any) -> np.ndarray | None:
        if frame is None:
            return None
        try:
            height = frame.shape[0]
            original_width = frame.shape[1]
            aspect = self._resize_width / max(1, original_width)
            new_height = max(1, int(height * aspect))
            self._scale_x = original_width / self._resize_width
            self._scale_y = height / max(1, new_height)
            resized = cv2.resize(frame, (self._resize_width, new_height))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            return gray
        except Exception:
            return None

    def _clean_mask(self, mask: np.ndarray) -> np.ndarray:
        kernel_size = max(1, self._morph_kernel_size)
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (kernel_size, kernel_size),
        )
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        return cv2.morphologyEx(opened, cv2.MORPH_DILATE, kernel, iterations=1)

    def _extract_regions(self, thresh: np.ndarray) -> list[tuple[int, int, int, int]]:
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        regions: list[tuple[int, int, int, int]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self._min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            x1 = int(round(x * self._scale_x))
            y1 = int(round(y * self._scale_y))
            x2 = int(round((x + w) * self._scale_x))
            y2 = int(round((y + h) * self._scale_y))
            regions.append((x1, y1, x2, y2))
        return regions
