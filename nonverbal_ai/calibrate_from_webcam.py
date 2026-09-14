"""
웹캠 캘리브레이션 캡처 스크립트 (로컬 실행 전용 - 웹캠 + 마이크 필요)

[목적]
    세션 시작 전, "카메라를 봐주세요" 안내와 함께 정해진 문장을 소리내어 읽는 짧은 구간을
    웹캠+마이크로 동시에 녹화하고, 얼굴/자세/음성 CalibrationProfile을 만들어 저장한다.

[설계 방침]
    mediapipe/librosa 분석 로직을 여기서 새로 짜지 않는다. 웹캠+마이크에서 짧게 녹화 ->
    임시 mp4/wav로 저장 -> nonverbal_analysis_v3.extract_calibration_profile()을 그대로
    재사용해서 분석한다 (파일 기반 로직과 웹캠 기반 로직이 따로 놀면 나중에 한쪽만 고치고
    잊어버리는 사고가 나기 쉬워서 "웹캠 = 짧은 녹화 + 기존 파일 분석 함수 재사용"으로 통일함).

[추가 의존성 - 마이크 녹음용]
    pip install sounddevice soundfile --break-system-packages
    (Linux는 시스템에 portaudio가 필요할 수 있음: apt install libportaudio2)

[사용법]
    python calibrate_from_webcam.py
    -> calibration_profile.json 파일이 생성됨 (is_valid=False여도 일단 저장됨 - 소프트 게이트)

    이후 본 답변 분석 시:
        from calibrate_from_webcam import load_calibration_profile
        calibration = load_calibration_profile()
        result = analyze_video(answer_video_path, audio_path=answer_audio_path, calibration=calibration)

[동작 흐름]
    1. 웹캠/마이크 연결 확인
    2. 3초 카운트다운
    3. CALIBRATION_CLIP_DURATION_SEC(기본 4초) 동안 "카메라를 보면서 이 문장을 읽어주세요"
       안내와 함께 영상+음성 동시 녹화
    4. extract_calibration_profile(video, audio)로 분석 -> is_valid / voice_calibration_valid 확인
       - 얼굴/자세가 유효(is_valid): JSON 저장 후 종료
       - 무효: 사유를 콘솔에 안내하고 재시도 (최대 MAX_RETRIES회)
       - 음성(voice_calibration_valid)은 별도 축이라, 얼굴/자세가 유효해도 음성만 실패할 수
         있음 - 이 경우도 프로파일은 저장하되 "음성 baseline 없음" 상태로 남고, 본 분석에서
         음성 상대값(volume_relative_db 등) 계산만 건너뛴다 (하드 블록 아님).
    5. 최종 profile을 calibration_profile.json으로 저장 (analyze_video 호출 시 재사용)

[주의 - 스켈레톤 단계 한계]
    - 카운트다운/안내 문구는 OpenCV 창(cv2.imshow)에 텍스트로 표시. 실제 서비스에서는
      Frontend가 이 안내 UI를 담당하게 될 것이므로, 이 스크립트는 로컬 검증/단독 실행용.
    - 재시도 횟수(3회), 캘리브레이션 길이(4초)는 임의 값. PM/Frontend와 협의 후 조정.
    - 마이크 샘플레이트는 16kHz로 고정. 웹캠 마이크가 이를 지원 안 하면 sounddevice가
      예외를 던짐 - 그 경우 CALIBRATION_AUDIO_SAMPLE_RATE 값을 44100 등으로 바꿔볼 것.
"""

import os
import time
import json
from dataclasses import asdict
from typing import Optional

from nonverbal_analysis_v3 import (
    CalibrationProfile,
    CALIBRATION_CLIP_DURATION_SEC,
    CALIBRATION_SCRIPT_TEXT,
    extract_calibration_profile,
)

MAX_RETRIES = 3
TEMP_CLIP_PATH = "_calibration_temp.mp4"
TEMP_AUDIO_PATH = "_calibration_temp_audio.wav"
PROFILE_OUTPUT_PATH = "calibration_profile.json"
CALIBRATION_AUDIO_SAMPLE_RATE = 16000


def save_calibration_profile(profile: CalibrationProfile, path: str = PROFILE_OUTPUT_PATH) -> None:
    """CalibrationProfile을 JSON으로 저장 (다음 실행/분석 시 재사용)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, ensure_ascii=False, indent=2)


def load_calibration_profile(path: str = PROFILE_OUTPUT_PATH) -> CalibrationProfile:
    """저장해둔 캘리브레이션 결과를 불러온다. analyze_video(..., calibration=이 값)으로 사용."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return CalibrationProfile(**data)


def _countdown(cap, seconds: int = 3) -> None:
    """cv2 창에 카운트다운 표시 (본 녹화 전에 마음의 준비 시간)."""
    import cv2
    for remaining in range(seconds, 0, -1):
        ret, frame = cap.read()
        if not ret:
            continue
        cv2.putText(frame, str(remaining), (30, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 200, 255), 3)
        cv2.putText(frame, "잠시 후 캘리브레이션이 시작됩니다", (30, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.imshow("캘리브레이션 - 정면을 응시해주세요", frame)
        cv2.waitKey(1000)


def _record_clip_with_audio(cap, video_out_path: str, audio_out_path: str, duration_sec: float) -> None:
    """
    웹캠+마이크에서 duration_sec만큼 동시에 녹화한다.
    - 영상: out_path(mp4)로 저장. 화면엔 "카메라를 보면서 문장을 읽어주세요" 오버레이를
      얹지만, 저장은 오버레이 없는 원본 프레임으로 한다(오버레이 텍스트가 얼굴 위에
      겹쳐 mediapipe 인식을 방해하지 않도록).
    - 음성: sounddevice.rec()이 백그라운드 스레드에서 즉시 녹음을 시작하므로(non-blocking),
      아래 영상 녹화 루프와 자연스럽게 같은 시간 동안 동시 진행된다.
    """
    import cv2
    import sounddevice as sd
    import soundfile as sf

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_out_path, fourcc, fps, (w, h))

    sr = CALIBRATION_AUDIO_SAMPLE_RATE
    audio_buffer = sd.rec(int(duration_sec * sr), samplerate=sr, channels=1, dtype="float32")

    start = time.time()
    while time.time() - start < duration_sec:
        ret, frame = cap.read()
        if not ret:
            break
        remaining = duration_sec - (time.time() - start)

        overlay = frame.copy()
        cv2.putText(overlay, "카메라를 보면서 아래 문장을 소리내어 읽어주세요", (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.putText(overlay, f'"{CALIBRATION_SCRIPT_TEXT}"', (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        cv2.putText(overlay, f"{remaining:.1f}s 남음", (20, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.imshow("캘리브레이션 - 정면을 응시하며 문장을 읽어주세요", overlay)

        writer.write(frame)  # 오버레이 없는 원본만 저장
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    writer.release()
    sd.wait()  # 녹음이 duration_sec만큼 끝날 때까지 대기 (영상 루프와 거의 동시에 끝나 있을 것)
    sf.write(audio_out_path, audio_buffer, sr)


def run_calibration(camera_index: int = 0) -> Optional[CalibrationProfile]:
    """
    웹캠+마이크 캘리브레이션 전체 흐름을 실행하고 최종 CalibrationProfile을 반환 + JSON 저장한다.
    [입력] camera_index: 웹캠이 여러 개면 0, 1, 2... 순서로 바꿔가며 시도
    [출력] CalibrationProfile (얼굴/자세가 단 한 번도 감지되지 않았으면 예외 발생)
    """
    import cv2

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(
            "웹캠을 열 수 없습니다. 카메라가 연결돼 있는지, 다른 프로그램이 카메라를 "
            "점유하고 있지 않은지, OS 카메라 권한이 허용됐는지 확인하세요."
        )

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    expected_frame_count = int(round(CALIBRATION_CLIP_DURATION_SEC * fps))

    profile: Optional[CalibrationProfile] = None
    try:
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"[캘리브레이션 시도 {attempt}/{MAX_RETRIES}]")
            _countdown(cap, seconds=3)
            _record_clip_with_audio(cap, TEMP_CLIP_PATH, TEMP_AUDIO_PATH, CALIBRATION_CLIP_DURATION_SEC)

            try:
                profile = extract_calibration_profile(
                    TEMP_CLIP_PATH,
                    calibration_audio_path=TEMP_AUDIO_PATH,
                    expected_frame_count=expected_frame_count,
                )
            except ValueError as e:
                print(f"  -> 얼굴/자세를 전혀 감지하지 못했습니다: {e}")
                continue

            print(f"  -> [얼굴/자세] is_valid={profile.is_valid} / {profile.validation_message} "
                  f"(detection_rate={profile.detection_rate})")
            print(f"  -> [음성] voice_calibration_valid={profile.voice_calibration_valid} / "
                  f"{profile.voice_calibration_message}")

            if profile.is_valid:
                break
            print("  -> 얼굴/자세 기준이 무효라 재시도합니다. (음성만 실패한 경우는 재시도하지 않음 - "
                  "아래 [경고] 참고)")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        for temp_path in (TEMP_CLIP_PATH, TEMP_AUDIO_PATH):
            if os.path.exists(temp_path):
                os.remove(temp_path)

    if profile is None:
        raise RuntimeError("캘리브레이션에 실패했습니다 (얼굴/자세가 한 번도 감지되지 않음).")

    if not profile.is_valid:
        print(f"[경고] {MAX_RETRIES}회 재시도 후에도 얼굴/자세 캘리브레이션 품질이 낮습니다. "
              f"is_valid=False로 저장하고 진행합니다 - 본 분석 리포트에 '신뢰도 낮음' "
              f"안내가 함께 표시됩니다 (하드 블록 아님, 소프트 게이트).")
    if not profile.voice_calibration_valid:
        print(f"[경고] 음성 캘리브레이션이 실패했습니다 ({profile.voice_calibration_message}). "
              f"본 분석에서 음량/피치/발화속도 상대값(volume_relative_db 등)은 계산되지 않고 "
              f"절대값만 제공됩니다.")

    save_calibration_profile(profile)
    print(f"캘리브레이션 완료 -> {PROFILE_OUTPUT_PATH}에 저장됨.")
    return profile


if __name__ == "__main__":
    run_calibration()
