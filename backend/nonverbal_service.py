"""로컬 데모용 비언어 AI 브리지.

`nonverbal_ai/` 폴더의 기존 분석기를 FastAPI 백엔드에서 안전하게 호출합니다.
최종 전달 안정성 점수는 만들지 않습니다. 현재 역할은 다음과 같습니다.

1. 답변 영상/음성을 실제 비언어 분석기로 측정
2. score-ready `stability_features`와 `delivery_profile_v1` 생성
3. 캘리브레이션이 없으면 시선/자세는 자동으로 score_eligible=False 유지
4. 오디오 품질이 나쁘면 measurement_unavailable로 표시
5. 얼굴/영상 분석이 실패해도 오디오 품질 검사는 가능한 한 별도로 살림
6. 타임라인 이벤트 중 정책상 안전한 이벤트만 Backend에 넘김

캘리브레이션 웹 연결 전에는 시선/자세 이벤트를 사용자 리포트에 저장하지 않습니다.
통합 규격은 integration_contract_v1.py를 기준으로 합니다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from integration_contract_v1 import (
    LEGACY_EXCLUDED_EVENT_TYPES,
    UNCALIBRATED_ALLOWED_DELIVERY_EVENT_TYPES,
    normalize_delivery_profile,
)

import os

# nonverbal_ai/ 폴더 위치를 찾는 순서:
#   1) NONVERBAL_AI_DIR 환경변수가 있으면 그 폴더의 "부모"를 sys.path에 추가
#      (예: NONVERBAL_AI_DIR=C:\projects\Note1\nonverbal_ai)
#   2) 없으면 backend에서 위로 올라가며 nonverbal_ai 폴더를 자동으로 탐색
#      (팀원들이 폴더 구조를 조금씩 다르게 두거나, 프로젝트 폴더를 통째로
#      옮기는 경우가 많아서 2~4단계 위까지 넉넉하게 찾는다)
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
    # insert(0, ...)가 아니라 append(...)를 쓴다. insert(0, ...)로 넣으면
    # Note1(저장소 루트)이 backend 자신보다 먼저 검색되어, backend/rag_ai와
    # 이름이 같은 최상위 rag_ai가 있을 때 그쪽이 잘못 로드되는 문제가 있었다
    # (실제로 이 버그로 backend/rag_ai/rag_ai_service.py를 고쳤는데도 예전
    # 최상위 버전이 계속 로드되는 문제가 발생했다). append로 맨 뒤에 추가하면
    # backend 안의 패키지가 항상 우선한다.
    sys.path.append(str(_REPO_ROOT))

_ANALYZER = None
_MAP_TO_DB = None
_DERIVE_FEATURES = None
_BUILD_PROFILE = None
_CHECK_AUDIO_QUALITY = None
_CALIBRATION_PROFILE_CLS = None
_INIT_ERROR: str | None = None


def _load_modules() -> None:
    global _ANALYZER, _MAP_TO_DB, _DERIVE_FEATURES, _BUILD_PROFILE, _CHECK_AUDIO_QUALITY, _CALIBRATION_PROFILE_CLS, _INIT_ERROR
    if _ANALYZER is not None or _INIT_ERROR is not None:
        return
    try:
        from nonverbal_ai.nonverbal_analysis_v3 import (
            analyze_video,
            map_to_db_fields,
            check_audio_quality_from_file,
            CalibrationProfile,
        )
        from nonverbal_ai.stability_features import derive_stability_features
        from nonverbal_ai.delivery_stability_v1 import build_delivery_profile

        _ANALYZER = analyze_video
        _MAP_TO_DB = map_to_db_fields
        _CHECK_AUDIO_QUALITY = check_audio_quality_from_file
        _DERIVE_FEATURES = derive_stability_features
        _BUILD_PROFILE = build_delivery_profile
        _CALIBRATION_PROFILE_CLS = CalibrationProfile
    except Exception as exc:  # noqa: BLE001
        _INIT_ERROR = f"비언어 AI 모듈 로드 실패: {exc}"


def build_calibration_object(visual_baseline: dict | None, audio_baseline: dict | None):
    """CALIBRATION_PROFILES에 저장된 baseline dict를 nonverbal_ai.CalibrationProfile로 복원.

    이미 calibration_status == "passed"인 세션에서만 호출한다고 가정하므로
    is_valid/voice_calibration_valid는 True로 채운다 (재검증이 아니라 baseline
    값을 답변 분석에 전달하려는 목적).
    """
    _load_modules()
    if _CALIBRATION_PROFILE_CLS is None or not visual_baseline:
        return None
    visual_baseline = visual_baseline or {}
    audio_baseline = audio_baseline or {}
    required = (
        "yaw_baseline", "pitch_baseline", "roll_baseline", "gaze_baseline",
        "ear_baseline", "smile_baseline", "landmark_motion_baseline",
        "shoulder_width_baseline", "shoulder_angle_baseline",
    )
    if any(visual_baseline.get(key) is None for key in required):
        return None
    try:
        return _CALIBRATION_PROFILE_CLS(
            yaw_baseline=visual_baseline["yaw_baseline"],
            pitch_baseline=visual_baseline["pitch_baseline"],
            roll_baseline=visual_baseline["roll_baseline"],
            gaze_baseline=visual_baseline["gaze_baseline"],
            ear_baseline=visual_baseline["ear_baseline"],
            smile_baseline=visual_baseline["smile_baseline"],
            landmark_motion_baseline=visual_baseline["landmark_motion_baseline"],
            shoulder_width_baseline=visual_baseline["shoulder_width_baseline"],
            shoulder_angle_baseline=visual_baseline["shoulder_angle_baseline"],
            is_valid=True,
            validation_message="세션 캘리브레이션에서 복원됨",
            detection_rate=visual_baseline.get("detection_rate") or 1.0,
            voice_mean_db_baseline=audio_baseline.get("voice_mean_db_baseline"),
            voice_f0_mean_baseline=audio_baseline.get("voice_f0_mean_baseline"),
            voice_f0_std_baseline=audio_baseline.get("voice_f0_std_baseline"),
            speaking_speed_baseline=audio_baseline.get("speaking_speed_baseline"),
            voice_calibration_valid=audio_baseline.get("voice_mean_db_baseline") is not None,
            voice_calibration_message="세션 캘리브레이션에서 복원됨",
        )
    except Exception:  # noqa: BLE001
        return None


def is_ready() -> bool:
    _load_modules()
    return _ANALYZER is not None


def init_error() -> str | None:
    _load_modules()
    return _INIT_ERROR


def _word_timestamp_pairs(detail: dict | None) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for item in (detail or {}).get("words") or []:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "").strip()
        start = item.get("start")
        if word and isinstance(start, (int, float)):
            pairs.append((word, float(start)))
    return pairs


def _to_wav_if_possible(audio_path: str) -> tuple[str, str | None]:
    """librosa가 안정적으로 읽도록 ffmpeg가 있으면 임시 WAV로 변환합니다."""
    if Path(audio_path).suffix.lower() == ".wav":
        return audio_path, None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return audio_path, None

    tmp = tempfile.NamedTemporaryFile(prefix="aisk_nonverbal_", suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                tmp_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return tmp_path, tmp_path
    except Exception:  # noqa: BLE001
        Path(tmp_path).unlink(missing_ok=True)
        return audio_path, None


def _safe_audio_quality(audio_path: str) -> dict | None:
    if _CHECK_AUDIO_QUALITY is None:
        return None
    try:
        return _CHECK_AUDIO_QUALITY(audio_path)
    except Exception:  # noqa: BLE001
        return None


def _filter_events(raw: dict) -> list[dict[str, Any]]:
    events = raw.get("events") or []
    calibration_used = bool(raw.get("calibration_used", False))
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        if event_type in LEGACY_EXCLUDED_EVENT_TYPES:
            continue
        if calibration_used or event_type in UNCALIBRATED_ALLOWED_DELIVERY_EVENT_TYPES:
            out.append(event)
    return out


def analyze_answer_delivery(
    *,
    video_path: str | None,
    audio_path: str,
    stt_text: str,
    stt_detail: dict | None,
    stt_features: dict | None,
    duration_sec: int | float | None,
    calibration=None,
) -> dict:
    """한 답변을 분석해 최종 점수 전 단계의 canonical delivery_profile을 반환합니다."""
    _load_modules()
    if _ANALYZER is None:
        return {
            "status": "unavailable",
            "reason": _INIT_ERROR or "비언어 AI가 준비되지 않았습니다.",
            "delivery_profile": None,
            "audio_quality": None,
            "events": [],
        }

    analysis_audio_path, tmp_wav = _to_wav_if_possible(audio_path)
    audio_quality = _safe_audio_quality(analysis_audio_path)

    if not video_path:
        if tmp_wav:
            Path(tmp_wav).unlink(missing_ok=True)
        return {
            "status": "unavailable",
            "reason": "답변 영상이 없어 시선·자세 비언어 분석을 실행하지 않았습니다.",
            "delivery_profile": None,
            "audio_quality": audio_quality,
            "events": [],
        }

    try:
        raw = _ANALYZER(
            video_path,
            audio_path=analysis_audio_path,
            stt_text=stt_text,
            word_timestamps=_word_timestamp_pairs(stt_detail),
            calibration=calibration,
        )
        if raw.get("audio_quality") is None and audio_quality is not None:
            raw["audio_quality"] = audio_quality

        features = _DERIVE_FEATURES(raw, duration_sec=duration_sec)
        delivery_profile = normalize_delivery_profile(
            _BUILD_PROFILE(raw, features, stt_features or {})
        )

        legacy_metrics = _MAP_TO_DB(raw)
        legacy_metrics["filler_word_count"] = None

        return {
            "status": "available",
            "reason": None,
            "delivery_profile": delivery_profile,
            "legacy_metrics": legacy_metrics,
            "events": _filter_events(raw),
            "audio_quality": raw.get("audio_quality") or audio_quality,
            "calibration_used": bool(raw.get("calibration_used", False)),
            "calibration_valid": raw.get("calibration_valid"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "reason": f"비언어 영상 분석 실패: {exc}",
            "delivery_profile": None,
            "audio_quality": audio_quality,
            "events": [],
        }
    finally:
        if tmp_wav:
            Path(tmp_wav).unlink(missing_ok=True)
