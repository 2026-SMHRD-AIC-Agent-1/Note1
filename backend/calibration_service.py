"""캘리브레이션 브리지 (A안: 짧게 녹화 후 업로드 → 서버에서 판정).

실시간 웹캠 스트리밍(B안) 대신, 프론트에서 3~5초 정도 "화면 중앙을 보고
문장을 읽는" 짧은 클립을 녹화해 통째로 업로드하면 서버가 한 번에 분석해
통과/실패를 돌려주는 방식이다.

실제 판정 로직(mediapipe/librosa)은 nonverbal_ai/nonverbal_analysis_v3.py의
extract_calibration_profile() / check_audio_quality_from_file()을 그대로
재사용하고, 결과를 integration_contract_v1.build_calibration_contract()로
Backend 공통 저장 형식으로 변환한다.

주의 (한계):
    현재 nonverbal_ai 분석기는 "얼굴 전체가 잡혔는지" 여부만 하나의 메시지로
    판정하며, "두 눈"과 "두 어깨"를 각각 따로 구분해서 실패 코드를 내지는
    않는다. 그래서 이 다리 코드는 얼굴/자세가 불충분할 때 FACE_NOT_FULLY_VISIBLE
    (필요하면 VISUAL_DETECTION_LOW도 함께)로 합쳐서 보고한다. EYES_NOT_BOTH_VISIBLE,
    SHOULDERS_NOT_BOTH_VISIBLE처럼 더 구체적인 코드가 필요하면 비언어 AI 쪽에서
    눈/어깨 각각의 검출 여부를 별도 신호로 추가해야 한다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from integration_contract_v1 import build_calibration_contract

import os

# nonverbal_ai/ 위치 탐색: nonverbal_service.py와 동일한 정책.
#   1) NONVERBAL_AI_DIR 환경변수 우선
#   2) 없으면 backend에서 위로 올라가며 nonverbal_ai 폴더를 자동 탐색
_env_dir = os.environ.get("NONVERBAL_AI_DIR")
if _env_dir:
    _REPO_ROOT = Path(_env_dir).resolve().parent
else:
    _here = Path(__file__).resolve()
    _REPO_ROOT = None
    for _candidate in list(_here.parents)[:5]:
        if (_candidate / "nonverbal_ai").is_dir():
            _REPO_ROOT = _candidate
            break
    if _REPO_ROOT is None:
        _REPO_ROOT = _here.parents[2] if len(_here.parents) > 2 else _here.parent

if str(_REPO_ROOT) not in sys.path:
    # insert(0, ...) 대신 append(...) — 이유는 nonverbal_service.py의 동일 주석 참고.
    # Note1을 최우선 검색 경로로 넣으면 backend/rag_ai 대신 최상위 rag_ai가
    # 잘못 로드되는 문제가 있었다.
    sys.path.append(str(_REPO_ROOT))

_EXTRACT_CALIBRATION_PROFILE = None
_CHECK_AUDIO_QUALITY = None
_INIT_ERROR: str | None = None

# [수정 2026-09-16] 예전엔 duration_sec * ASSUMED_FPS(30)로 "기대 프레임 수"를
# 추측해서 넘겼는데, 실제 웹캠 녹화는 브라우저/장치에 따라 초당 30프레임이
# 아닌 경우(예: 10fps)가 흔해서 detection_rate가 실제보다 훨씬 낮게(예: 0.33)
# 잘못 계산되는 문제가 있었다. expected_frame_count를 넘기지 않으면
# extract_calibration_profile()이 영상에서 실제로 읽은 프레임 수를 기준으로
# detection_rate를 계산하므로 훨씬 정확하다.


def _load_modules() -> None:
    global _EXTRACT_CALIBRATION_PROFILE, _CHECK_AUDIO_QUALITY, _INIT_ERROR
    if _EXTRACT_CALIBRATION_PROFILE is not None or _INIT_ERROR is not None:
        return
    try:
        from nonverbal_ai.nonverbal_analysis_v3 import (
            extract_calibration_profile,
            check_audio_quality_from_file,
        )

        _EXTRACT_CALIBRATION_PROFILE = extract_calibration_profile
        _CHECK_AUDIO_QUALITY = check_audio_quality_from_file
    except Exception as exc:  # noqa: BLE001
        _INIT_ERROR = f"캘리브레이션 분석 모듈 로드 실패: {exc}"


def is_ready() -> bool:
    _load_modules()
    return _EXTRACT_CALIBRATION_PROFILE is not None


def init_error() -> str | None:
    _load_modules()
    return _INIT_ERROR


def _extract_audio_track(video_path: str) -> str | None:
    """webm/mp4 등 영상 파일에서 오디오 트랙만 wav로 뽑아낸다. ffmpeg 필요."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    tmp = tempfile.NamedTemporaryFile(prefix="aisk_calibration_audio_", suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", video_path, "-ac", "1", "-ar", "16000", tmp_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return tmp_path
    except Exception:  # noqa: BLE001
        Path(tmp_path).unlink(missing_ok=True)
        return None


def _map_visual_failure_reasons(profile: Any) -> list[str]:
    """profile.validation_message / detection_rate를 통합 규격 실패 코드로 매핑.

    (한계) 위 모듈 docstring 참고 — 눈/어깨 개별 판정은 아직 지원하지 않는다.
    """
    reasons: list[str] = []
    if profile is None:
        return reasons
    message = getattr(profile, "validation_message", "") or ""
    detection_rate = getattr(profile, "detection_rate", None)

    if "화면에 충분히 잡히지" in message:
        reasons.append("FACE_NOT_FULLY_VISIBLE")
    if "움직임이 감지" in message:
        reasons.append("VISUAL_NOT_STABLE")
    if isinstance(detection_rate, (int, float)) and detection_rate < 0.8:
        reasons.append("VISUAL_DETECTION_LOW")
    return reasons


def run_calibration(
    *,
    video_path: str,
    duration_sec: float | None,
) -> dict[str, Any]:
    """짧은 캘리브레이션 클립(영상+오디오 한 파일)을 분석해 저장용 dict를 반환한다."""
    _load_modules()
    if _EXTRACT_CALIBRATION_PROFILE is None:
        return build_calibration_contract(technical_error=_INIT_ERROR or "캘리브레이션 서비스가 준비되지 않았습니다.")

    audio_path = _extract_audio_track(video_path)
    profile = None
    audio_quality = None
    try:
        # expected_frame_count는 일부러 넘기지 않는다 (위 설명 참고) —
        # 영상에서 실제로 읽힌 프레임 수를 기준으로 detection_rate를 계산한다.
        profile = _EXTRACT_CALIBRATION_PROFILE(
            calibration_video_path=video_path,
            calibration_audio_path=audio_path,
            expected_frame_count=None,
        )
        if audio_path and _CHECK_AUDIO_QUALITY is not None:
            try:
                audio_quality = _CHECK_AUDIO_QUALITY(audio_path)
            except Exception:  # noqa: BLE001
                audio_quality = None
    except Exception as exc:  # noqa: BLE001
        return build_calibration_contract(technical_error=f"캘리브레이션 분석 실패: {exc}")
    finally:
        if audio_path:
            Path(audio_path).unlink(missing_ok=True)

    failure_reasons = _map_visual_failure_reasons(profile)

    # ffmpeg이 없거나 오디오 추출/품질검사가 실패해서 audio_status가
    # "not_run"으로 남는 경우, 이유 없이 그냥 실패로만 보이지 않도록
    # 명시적인 실패 코드를 추가한다.
    if audio_path is None:
        failure_reasons.append("AUDIO_CAPTURE_ERROR")
    elif audio_quality is None:
        failure_reasons.append("AUDIO_CALIBRATION_FAILED")

    return build_calibration_contract(profile, audio_quality=audio_quality, failure_reasons=failure_reasons)
