"""A!SK V1 webcam calibration runner (local validation tool).

Product policy implemented here:
1) Visual calibration is a hard gate. The user must keep full face, both eyes,
   and both shoulders in frame while looking at the screen-center target for
   3 continuous seconds. If the captured baseline fails motion/detection QA,
   the stage repeats until it passes or the user cancels.
2) Audio calibration is a separate environment check. The user reads the fixed
   sentence once. We verify microphone/noise quality and save only a baseline
   volume for report reference; pitch/reading-speed are not calibration scores.
3) The interview must not start until both stages pass.

The real service frontend should render the same states in browser UI. This file
is the local webcam reference implementation used to validate the contract.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
from typing import Optional

try:
    from calibration_policy_v1 import (
        AUDIO_SCRIPT_TEXT,
        VISUAL_STABLE_DURATION_SEC,
    )
except ImportError:  # package-style import
    from .calibration_policy_v1 import (
        AUDIO_SCRIPT_TEXT,
        VISUAL_STABLE_DURATION_SEC,
    )

from nonverbal_analysis_v3 import (
    CalibrationProfile,
    analyze_volume,
    check_audio_quality_from_file,
    extract_calibration_profile,
)

TEMP_VISUAL_CLIP_PATH = "_calibration_visual_temp.mp4"
TEMP_AUDIO_PATH = "_calibration_audio_temp.wav"
PROFILE_OUTPUT_PATH = "calibration_profile.json"
CALIBRATION_AUDIO_SAMPLE_RATE = 16000

# Technical recording window only. Reading speed is NOT scored or calibrated.
AUDIO_CAPTURE_WINDOW_SEC = 6.0
FRAME_MARGIN = 0.03


def save_calibration_profile(profile: CalibrationProfile, path: str = PROFILE_OUTPUT_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, ensure_ascii=False, indent=2)


def load_calibration_profile(path: str = PROFILE_OUTPUT_PATH) -> CalibrationProfile:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return CalibrationProfile(**data)


def _countdown(cap, seconds: int = 3) -> None:
    import cv2

    for remaining in range(seconds, 0, -1):
        ret, frame = cap.read()
        if not ret:
            continue
        cv2.putText(frame, str(remaining), (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 200, 255), 3)
        cv2.putText(frame, "Calibration starts soon", (30, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)
        cv2.imshow("A!SK Calibration", frame)
        if cv2.waitKey(1000) & 0xFF == ord("q"):
            raise KeyboardInterrupt


def _in_frame(lm, margin: float = FRAME_MARGIN) -> bool:
    return margin <= lm.x <= (1.0 - margin) and margin <= lm.y <= (1.0 - margin)


def _record_visual_calibration(cap, out_path: str, stable_sec: float) -> int:
    """Capture exactly one continuous ready window and save it as a clip.

    Real-time readiness checks the product-agreed framing requirements:
    - full face proxy landmarks are inside the frame
    - both eyes are inside the frame
    - both shoulders are visible and inside the frame

    The screen-center target is displayed throughout. Fine-grained movement
    stability is validated again after capture by extract_calibration_profile().
    """
    import cv2
    import mediapipe as mp

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    required_frames = max(1, int(round(stable_sec * fps)))

    mp_face = mp.solutions.face_mesh
    mp_pose = mp.solutions.pose

    # Face proxy landmarks: top, chin, left/right side; eye corners.
    face_outline_ids = (10, 152, 234, 454)
    eye_ids = (33, 133, 362, 263)

    ready_frames = []

    with mp_face.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as face_mesh, mp_pose.Pose(
        static_image_mode=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as pose:
        while True:
            ret, frame = cap.read()
            if not ret:
                ready_frames = []
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_result = face_mesh.process(rgb)
            pose_result = pose.process(rgb)

            face_ok = False
            eyes_ok = False
            shoulders_ok = False

            if face_result.multi_face_landmarks:
                lm = face_result.multi_face_landmarks[0].landmark
                face_ok = all(_in_frame(lm[i]) for i in face_outline_ids)
                eyes_ok = all(_in_frame(lm[i]) for i in eye_ids)

            if pose_result.pose_landmarks:
                plm = pose_result.pose_landmarks.landmark
                left_sh = plm[11]
                right_sh = plm[12]
                shoulders_ok = (
                    left_sh.visibility >= 0.5
                    and right_sh.visibility >= 0.5
                    and _in_frame(left_sh)
                    and _in_frame(right_sh)
                )

            frame_ready = face_ok and eyes_ok and shoulders_ok
            if frame_ready:
                ready_frames.append(frame.copy())
            else:
                ready_frames = []

            progress_sec = min(stable_sec, len(ready_frames) / fps)
            display = frame.copy()
            cx, cy = w // 2, h // 2
            cv2.circle(display, (cx, cy), 12, (0, 255, 255), 2)
            cv2.circle(display, (cx, cy), 3, (0, 255, 255), -1)

            cv2.putText(display, "LOOK AT THE CENTER TARGET", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(display, f"FACE/EYES: {'OK' if face_ok and eyes_ok else 'ADJUST'}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0) if face_ok and eyes_ok else (0, 0, 255), 2)
            cv2.putText(display, f"SHOULDERS: {'OK' if shoulders_ok else 'ADJUST'}", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0) if shoulders_ok else (0, 0, 255), 2)
            cv2.putText(display, f"HOLD: {progress_sec:.1f}/{stable_sec:.1f}s", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0) if frame_ready else (0, 165, 255), 2)
            cv2.imshow("A!SK Calibration - Visual", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                raise KeyboardInterrupt

            if len(ready_frames) >= required_frames:
                break

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
    for frame in ready_frames[-required_frames:]:
        writer.write(frame)
    writer.release()
    return required_frames


def _record_audio_environment_check(cap, out_path: str) -> None:
    """Record the fixed sentence for environment QA only."""
    import cv2
    import sounddevice as sd
    import soundfile as sf

    sr = CALIBRATION_AUDIO_SAMPLE_RATE
    audio_buffer = sd.rec(
        int(AUDIO_CAPTURE_WINDOW_SEC * sr),
        samplerate=sr,
        channels=1,
        dtype="float32",
    )

    start = time.time()
    while time.time() - start < AUDIO_CAPTURE_WINDOW_SEC:
        ret, frame = cap.read()
        if not ret:
            continue
        remaining = AUDIO_CAPTURE_WINDOW_SEC - (time.time() - start)
        cv2.putText(frame, "READ THE FIXED SENTENCE ON SCREEN", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        # OpenCV's default font is not reliable for Korean; browser UI will show
        # AUDIO_SCRIPT_TEXT. Keep an ASCII reminder in the local validation window.
        cv2.putText(frame, f"Audio check: {remaining:.1f}s", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow("A!SK Calibration - Audio", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            sd.stop()
            raise KeyboardInterrupt

    sd.wait()
    sf.write(out_path, audio_buffer, sr)


def run_calibration(camera_index: int = 0) -> Optional[CalibrationProfile]:
    """Run the two-stage hard-gate calibration and save CalibrationProfile.

    This function intentionally has no retry limit. A failed calibration does
    not degrade into a low-confidence interview; it repeats until valid or the
    user explicitly cancels with Q.
    """
    import cv2

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(
            "웹캠을 열 수 없습니다. 카메라 연결, 다른 프로그램의 점유 여부, OS 권한을 확인해주세요."
        )

    profile: Optional[CalibrationProfile] = None
    try:
        print("[1단계] 시각 캘리브레이션 - 화면 중앙 표시점을 보며 3초 연속 안정 상태를 유지하세요.")
        while True:
            _countdown(cap, seconds=3)
            frame_count = _record_visual_calibration(
                cap,
                TEMP_VISUAL_CLIP_PATH,
                stable_sec=VISUAL_STABLE_DURATION_SEC,
            )
            try:
                profile = extract_calibration_profile(
                    TEMP_VISUAL_CLIP_PATH,
                    calibration_audio_path=None,
                    expected_frame_count=frame_count,
                )
            except ValueError as exc:
                print(f"  -> 시각 캘리브레이션 실패: {exc}")
                print("  -> 얼굴 전체/양쪽 눈/양쪽 어깨를 화면 안에 맞추고 다시 시도합니다.")
                continue

            if profile.is_valid:
                print(f"  -> 시각 캘리브레이션 통과 (detection_rate={profile.detection_rate})")
                break

            print(f"  -> 시각 캘리브레이션 재시도: {profile.validation_message}")

        print("[2단계] 음성 환경 확인")
        print(f"  -> 다음 문장을 한 번 읽어주세요: {AUDIO_SCRIPT_TEXT}")
        while True:
            _record_audio_environment_check(cap, TEMP_AUDIO_PATH)
            quality = check_audio_quality_from_file(TEMP_AUDIO_PATH)
            if not quality.get("is_valid"):
                issues = quality.get("issues") or []
                for issue in issues:
                    print(f"  -> {issue.get('message', issue.get('code'))}")
                print("  -> 마이크/주변 소음 환경을 조정하고 다시 시도합니다.")
                continue

            try:
                volume = analyze_volume(TEMP_AUDIO_PATH)
                baseline_db = volume.get("mean_db")
            except ValueError as exc:
                print(f"  -> 목소리 음량 기준을 만들 수 없습니다: {exc}")
                print("  -> 마이크에 자연스럽게 말한 뒤 다시 시도합니다.")
                continue

            # Audio calibration is environment-only. Save baseline volume for
            # relative reporting, but intentionally do not calibrate pitch/speed.
            profile = replace(
                profile,
                voice_mean_db_baseline=baseline_db,
                voice_f0_mean_baseline=None,
                voice_f0_std_baseline=None,
                speaking_speed_baseline=None,
                voice_calibration_valid=True,
                voice_calibration_message="정상 - 마이크/소음 환경 확인 완료",
            )
            print(f"  -> 음성 환경 확인 통과 (기본 음량 {baseline_db} dB, 점수 직접 반영 안 함)")
            break

        save_calibration_profile(profile)
        print(f"캘리브레이션 완료 -> {PROFILE_OUTPUT_PATH}")
        return profile

    except KeyboardInterrupt:
        print("캘리브레이션이 사용자에 의해 취소되었습니다. 면접은 시작하지 않습니다.")
        return None
    finally:
        cap.release()
        cv2.destroyAllWindows()
        for temp_path in (TEMP_VISUAL_CLIP_PATH, TEMP_AUDIO_PATH):
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    run_calibration()
