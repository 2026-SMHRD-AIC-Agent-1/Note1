"""로컬 데모용 비언어 AI 브리지.

`nonverbal_ai/` 폴더의 기존 분석기를 FastAPI 백엔드에서 안전하게 호출합니다.
최종 전달 안정성 점수는 만들지 않습니다. 현재 역할은 다음과 같습니다.

1. 답변 영상/음성을 실제 비언어 분석기로 측정
2. score-ready `stability_features`와 `delivery_profile_v1` 생성
3. 캘리브레이션이 없으면 시선/자세는 자동으로 score_eligible=False 유지
4. 오디오 품질이 나쁘면 measurement_unavailable로 표시
5. 타임라인 이벤트 중 정책상 안전한 이벤트만 Backend에 넘김

캘리브레이션 웹 연결 전에는 시선/자세 이벤트를 사용자 리포트에 저장하지 않습니다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ANALYZER = None
_MAP_TO_DB = None
_DERIVE_FEATURES = None
_BUILD_PROFILE = None
_INIT_ERROR: str | None = None

# 캘리브레이션 없이도 의미 있게 볼 수 있는 실제 음성 신호 기반 이벤트.
# 시선/자세는 캘리브레이션 연결 전에는 저장하지 않습니다.
AUDIO_EVENT_TYPES = {"LONG_PAUSE"}


def _load_modules() -> None:
    global _ANALYZER, _MAP_TO_DB, _DERIVE_FEATURES, _BUILD_PROFILE, _INIT_ERROR
    if _ANALYZER is not None or _INIT_ERROR is not None:
        return
    try:
        from nonverbal_ai.nonverbal_analysis_v3 import analyze_video, map_to_db_fields
        from nonverbal_ai.stability_features import derive_stability_features
        from nonverbal_ai.delivery_stability_v1 import build_delivery_profile

        _ANALYZER = analyze_video
        _MAP_TO_DB = map_to_db_fields
        _DERIVE_FEATURES = derive_stability_features
        _BUILD_PROFILE = build_delivery_profile
    except Exception as exc:  # noqa: BLE001
        _INIT_ERROR = f"비언어 AI 모듈 로드 실패: {exc}"


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


def _filter_events(raw: dict) -> list[dict[str, Any]]:
    events = raw.get("events") or []
    calibration_used = bool(raw.get("calibration_used", False))
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        # 기존 FILLER_WORD는 상세 STT의 '머뭇거림 표현' 이벤트와 중복되고
        # 문맥 오탐 가능성이 있어 저장하지 않습니다.
        if event_type == "FILLER_WORD":
            continue
        if calibration_used or event_type in AUDIO_EVENT_TYPES:
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
    """한 답변을 분석해 최종 점수 전 단계의 전달 profile을 반환합니다.

    `calibration=None`이면 시선/자세는 측정 참고값만 남고 점수 후보가 되지 않습니다.
    웹 캘리브레이션이 연결되면 같은 함수의 calibration 인자만 채우면 됩니다.
    """
    if not video_path:
        return {
            "status": "unavailable",
            "reason": "답변 영상이 없어 비언어 분석을 실행하지 않았습니다.",
            "delivery_profile": None,
            "events": [],
        }

    _load_modules()
    if _ANALYZER is None:
        return {
            "status": "unavailable",
            "reason": _INIT_ERROR or "비언어 AI가 준비되지 않았습니다.",
            "delivery_profile": None,
            "events": [],
        }

    analysis_audio_path, tmp_wav = _to_wav_if_possible(audio_path)
    try:
        raw = _ANALYZER(
            video_path,
            audio_path=analysis_audio_path,
            stt_text=stt_text,
            word_timestamps=_word_timestamp_pairs(stt_detail),
            calibration=calibration,
        )
        features = _DERIVE_FEATURES(raw, duration_sec=duration_sec)
        delivery_profile = _BUILD_PROFILE(raw, features, stt_features or {})

        # 기존 DB 14필드와의 호환값은 필요할 때만 참고할 수 있도록 반환합니다.
        # 머뭇거림 표현은 새 상세 STT가 담당하므로 legacy filler 값은 사용하지 않습니다.
        legacy_metrics = _MAP_TO_DB(raw)
        legacy_metrics["filler_word_count"] = None

        return {
            "status": "available",
            "reason": None,
            "delivery_profile": delivery_profile,
            "legacy_metrics": legacy_metrics,
            "events": _filter_events(raw),
            "audio_quality": raw.get("audio_quality"),
            "calibration_used": bool(raw.get("calibration_used", False)),
            "calibration_valid": raw.get("calibration_valid"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "reason": f"비언어 분석 실패: {exc}",
            "delivery_profile": None,
            "events": [],
        }
    finally:
        if tmp_wav:
            Path(tmp_wav).unlink(missing_ok=True)
