"""Pose landmarks from a video file, for `app.pipeline.swing`.

The only module in the project that imports a pose library. `swing.py` depends on the
`PoseSource` protocol and on `PoseFrame`, both of which are plain data, so the
measurement maths is tested with hand-written frames and no weights at all — which is
also why `make check` does not need this file to work.

**Weights.** MediaPipe Pose Landmarker, fetched to `spike/models/` by `make fetch-models`
and never downloaded at runtime: pulling in weights is a licence decision, not a cache
miss. The library is Apache 2.0 (verified from the LICENSE in the installed wheel,
2026-10-13). **The licence of the weights themselves is not yet verified** — Google
publishes the model card on ai.google.dev, which this environment's network policy
blocks. `config/providers.yaml` records that as unverified, and this is measurement only:
nothing from this model enters a render.

**Why VIDEO mode.** The landmarker's video mode carries state between frames, which
steadies a fast limb. Running each frame independently made the wrist jump between the
real hand and a background shape on three frames of a six-second test clip, and a single
spurious high wrist moves the peak — the one number the gate refuses on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from app.pipeline.swing import PoseFrame

#: BlazePose's 33-landmark layout. Named here rather than inline because an off-by-one
#: in this table would produce a plausible-looking number measured from the wrong joint.
LEFT_SHOULDER: Final = 11
RIGHT_SHOULDER: Final = 12
LEFT_WRIST: Final = 15
RIGHT_WRIST: Final = 16
LEFT_HIP: Final = 23
RIGHT_HIP: Final = 24

#: Below this landmark visibility, the position is a guess. Kept strict because an
#: invented wrist is worse than a missing one: a missing wrist costs coverage, which the
#: gate already refuses on, while an invented one can only push the peak up or down
#: silently.
MIN_VISIBILITY: Final = 0.5

#: Hard ceiling on frames analysed, so a long clip cannot turn into a long wait. 900 is
#: 30 seconds at 30 fps, which covers the longest clip any endpoint we use will return.
MAX_FRAMES: Final = 900


class MediapipePose:
    """Reads a video and returns one `PoseFrame` per frame, in order.

    Every sampled frame appears in the result, including frames where nothing was
    detected — an all-None frame. `SwingMeasurement.coverage` is the share that carried a
    usable pose, so dropping the empties here would make a clip with one good frame look
    fully covered.
    """

    def __init__(self, model_path: Path, *, min_visibility: float = MIN_VISIBILITY) -> None:
        self.model_path = Path(model_path)
        self.min_visibility = min_visibility
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"pose weights missing at {self.model_path}; run `make fetch-models`"
            )

    def _landmarker(self) -> Any:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
        )
        return vision.PoseLandmarker.create_from_options(options)

    def _to_frame(self, landmarks: list[Any]) -> PoseFrame:
        def y(index: int) -> float | None:
            point = landmarks[index]
            visibility = getattr(point, "visibility", 1.0)
            if visibility is not None and visibility < self.min_visibility:
                return None
            return float(point.y)

        return PoseFrame(
            left_shoulder_y=y(LEFT_SHOULDER),
            right_shoulder_y=y(RIGHT_SHOULDER),
            left_hip_y=y(LEFT_HIP),
            right_hip_y=y(RIGHT_HIP),
            left_wrist_y=y(LEFT_WRIST),
            right_wrist_y=y(RIGHT_WRIST),
        )

    def frames(self, video: Path) -> list[PoseFrame]:
        import cv2
        import mediapipe as mp

        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise FileNotFoundError(f"could not open {video}")
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        out: list[PoseFrame] = []
        try:
            with self._landmarker() as landmarker:
                index = 0
                while index < MAX_FRAMES:
                    ok, bgr = capture.read()
                    if not ok:
                        break
                    image = mp.Image(
                        image_format=mp.ImageFormat.SRGB,
                        data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB),
                    )
                    # Milliseconds, strictly increasing, which VIDEO mode requires.
                    result = landmarker.detect_for_video(image, int(index * 1000 / fps))
                    poses = getattr(result, "pose_landmarks", None) or []
                    out.append(self._to_frame(poses[0]) if poses else PoseFrame())
                    index += 1
        finally:
            capture.release()
        return out
