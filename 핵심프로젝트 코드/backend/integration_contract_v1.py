"""A!SK 팀 프로젝트 통합 규격 V1.

GitHub main을 최종 기준으로 삼기 위한 공통 이름/상태/이벤트 계약입니다.
기존 코드에 이미 사용 중인 이름은 유지하고, 앞으로 추가할 캘리브레이션·전달분석도
이 파일의 이름을 기준으로 구현합니다.

원칙
- snake_case 변수명 사용
- 기존 RAG/Backend/Frontend 필드는 유지
- 전달분석은 delivery_profile.components.* 구조 사용
- 측정 실패는 0점이 아니라 measurement_unavailable
- overall_score는 내용 종합 점수이며 전달점수와 합산하지 않음
"""
from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
from typing import Any

INTEGRATION_CONTRACT_VERSION = "aisk-integration-contract-v1"
CALIBRATION_VERSION = "aisk-calibration-nonverbal-v1"
DELIVERY_PROFILE_VERSION = "delivery-stability-v1-candidate.2"

# ------------------------------------------------------------------
# 캘리브레이션 상태
# ------------------------------------------------------------------
CALIBRATION_STATUS_PENDING = "pending"
CALIBRATION_STATUS_PASSED = "passed"
CALIBRATION_STATUS_FAILED = "failed"
CALIBRATION_STATUS_TECHNICAL_ERROR = "technical_error"

CALIBRATION_STAGE_NOT_RUN = "not_run"
CALIBRATION_STAGE_PASSED = "passed"
CALIBRATION_STAGE_FAILED = "failed"
CALIBRATION_STAGE_TECHNICAL_ERROR = "technical_error"

CALIBRATION_STATUS_VALUES = {
    CALIBRATION_STATUS_PENDING,
    CALIBRATION_STATUS_PASSED,
    CALIBRATION_STATUS_FAILED,
    CALIBRATION_STATUS_TECHNICAL_ERROR,
}
CALIBRATION_STAGE_STATUS_VALUES = {
    CALIBRATION_STAGE_NOT_RUN,
    CALIBRATION_STAGE_PASSED,
    CALIBRATION_STAGE_FAILED,
    CALIBRATION_STAGE_TECHNICAL_ERROR,
}

# 브라우저/실시간 안내 및 Backend 저장에 공통으로 쓰는 실패 코드.
CALIBRATION_FAILURE_CODES = {
    "FACE_NOT_FULLY_VISIBLE",
    "EYES_NOT_BOTH_VISIBLE",
    "SHOULDERS_NOT_BOTH_VISIBLE",
    "VISUAL_DETECTION_LOW",
    "VISUAL_NOT_STABLE",
    "MIC_SILENT",
    "TOO_NOISY",
    "LOW_SNR",
    "CAMERA_PERMISSION_DENIED",
    "MIC_PERMISSION_DENIED",
    "CAMERA_ERROR",
    "FRAME_READ_ERROR",
    "AUDIO_CAPTURE_ERROR",
    "VISUAL_CALIBRATION_FAILED",
    "AUDIO_CALIBRATION_FAILED",
}

# ------------------------------------------------------------------
# 전달분석 상태
# ------------------------------------------------------------------
MEASUREMENT_AVAILABLE = "available"
MEASUREMENT_UNAVAILABLE = "measurement_unavailable"
DELIVERY_ANALYSIS_AVAILABLE = "available"
DELIVERY_ANALYSIS_UNAVAILABLE = "unavailable"
DELIVERY_SCORE_POLICY_PENDING = "policy_pending"

# ------------------------------------------------------------------
# 타임라인 이벤트
# 현재 실제 nonverbal_ai가 생성하는 이름 + 상세 STT가 생성하는 이름을 기준으로 고정.
# FILLER_WORD는 레거시 원본 이벤트이며 사용자 타임라인에는 저장하지 않음.
# ------------------------------------------------------------------
STT_EVENT_TYPES = {
    "SPEECH_HESITATION",
    "SPEECH_REPETITION",
}

DELIVERY_EVENT_TYPES = {
    "GAZE_AWAY",
    "FACE_TURNED",
    "LONG_BLINK",
    "SMILE",
    "EXPRESSION_CHANGE",
    "NOD",
    "SHAKE",
    "BODY_MOVEMENT",
    "HAND_GESTURE",
    "LONG_PAUSE",
}

CORE_REPORT_EVENT_TYPES = {
    "GAZE_AWAY",
    "FACE_TURNED",
    "BODY_MOVEMENT",
    "LONG_PAUSE",
    "SPEECH_HESITATION",
    "SPEECH_REPETITION",
}

ALL_TIMELINE_EVENT_TYPES = STT_EVENT_TYPES | DELIVERY_EVENT_TYPES
UNCALIBRATED_ALLOWED_DELIVERY_EVENT_TYPES = {"LONG_PAUSE"}
LEGACY_EXCLUDED_EVENT_TYPES = {"FILLER_WORD"}

# ------------------------------------------------------------------
# CalibrationProfile -> Backend 공통 저장 구조
# 실제 nonverbal_ai.CalibrationProfile 필드명과 동일한 baseline 이름만 사용.
# ------------------------------------------------------------------
VISUAL_BASELINE_FIELDS = (
    "yaw_baseline",
    "pitch_baseline",
    "roll_baseline",
    "gaze_baseline",
    "ear_baseline",
    "smile_baseline",
    "landmark_motion_baseline",
    "shoulder_width_baseline",
    "shoulder_angle_baseline",
    "detection_rate",
)

AUDIO_BASELINE_FIELDS = (
    "voice_mean_db_baseline",
    # V1 정책상 아래 값은 점수 기준으로 사용하지 않지만 기존 CalibrationProfile의
    # 하위 호환을 위해 저장 가능하도록 필드명은 유지한다.
    "voice_f0_mean_baseline",
    "voice_f0_std_baseline",
    "speaking_speed_baseline",
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    out: dict[str, Any] = {}
    for key in (*VISUAL_BASELINE_FIELDS, *AUDIO_BASELINE_FIELDS, "is_valid", "validation_message", "voice_calibration_valid", "voice_calibration_message"):
        if hasattr(value, key):
            out[key] = getattr(value, key)
    return out


def build_calibration_contract(
    profile: Any = None,
    *,
    audio_quality: dict[str, Any] | None = None,
    failure_reasons: list[str] | None = None,
    technical_error: str | None = None,
) -> dict[str, Any]:
    """nonverbal_ai CalibrationProfile을 공통 Backend 저장 형식으로 변환합니다."""
    data = _as_mapping(profile)
    reasons = list(dict.fromkeys(failure_reasons or []))

    if technical_error:
        return {
            "calibration_version": CALIBRATION_VERSION,
            "calibration_status": CALIBRATION_STATUS_TECHNICAL_ERROR,
            "visual_status": CALIBRATION_STAGE_TECHNICAL_ERROR,
            "audio_status": CALIBRATION_STAGE_NOT_RUN,
            "visual_baseline": {},
            "audio_baseline": {},
            "audio_quality": audio_quality or {},
            "failure_reasons": reasons,
            "technical_error": technical_error,
        }

    visual_ran = bool(data)
    visual_passed = bool(data.get("is_valid")) if visual_ran else False
    audio_ran = data.get("voice_calibration_message") not in (None, "음성 캘리브레이션 미실행")
    audio_passed = bool(data.get("voice_calibration_valid")) if audio_ran else False

    for issue in (audio_quality or {}).get("issues") or []:
        if isinstance(issue, dict) and issue.get("code"):
            reasons.append(str(issue["code"]))

    if visual_ran and not visual_passed and not reasons:
        reasons.append("VISUAL_CALIBRATION_FAILED")
    if audio_ran and not audio_passed and not reasons:
        reasons.append("AUDIO_CALIBRATION_FAILED")
    reasons = list(dict.fromkeys(reasons))

    visual_status = (
        CALIBRATION_STAGE_PASSED if visual_passed
        else CALIBRATION_STAGE_FAILED if visual_ran
        else CALIBRATION_STAGE_NOT_RUN
    )
    audio_status = (
        CALIBRATION_STAGE_PASSED if audio_passed
        else CALIBRATION_STAGE_FAILED if audio_ran
        else CALIBRATION_STAGE_NOT_RUN
    )

    if visual_passed and audio_passed:
        calibration_status = CALIBRATION_STATUS_PASSED
    elif visual_ran or audio_ran:
        calibration_status = CALIBRATION_STATUS_FAILED
    else:
        calibration_status = CALIBRATION_STATUS_PENDING

    return {
        "calibration_version": CALIBRATION_VERSION,
        "calibration_status": calibration_status,
        "visual_status": visual_status,
        "audio_status": audio_status,
        "visual_baseline": {k: data.get(k) for k in VISUAL_BASELINE_FIELDS},
        "audio_baseline": {k: data.get(k) for k in AUDIO_BASELINE_FIELDS},
        "audio_quality": copy.deepcopy(audio_quality or {}),
        "failure_reasons": reasons,
        "technical_error": None,
    }


# ------------------------------------------------------------------
# delivery_profile 공통 구조 정규화
# 기존 nonverbal_ai.delivery_stability_v1의 구조를 그대로 기준으로 삼고,
# 향후 사용할 delivery_score 이름만 추가한다. legacy final_score는 유지.
# ------------------------------------------------------------------
def normalize_delivery_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return profile

    normalized = copy.deepcopy(profile)
    components = normalized.setdefault("components", {})

    # canonical key는 posture_stability. head_posture_stability는 하위 호환 alias.
    if "posture_stability" not in components and "head_posture_stability" in components:
        components["posture_stability"] = copy.deepcopy(components["head_posture_stability"])
    if "head_posture_stability" not in components and "posture_stability" in components:
        components["head_posture_stability"] = copy.deepcopy(components["posture_stability"])

    normalized.setdefault("version", DELIVERY_PROFILE_VERSION)
    normalized.setdefault("delivery_score", normalized.get("final_score"))
    normalized.setdefault(
        "delivery_score_status",
        normalized.get("final_score_status", DELIVERY_SCORE_POLICY_PENDING),
    )

    # 기존 소비자 호환을 위해 legacy key도 유지.
    normalized.setdefault("final_score", normalized.get("delivery_score"))
    normalized.setdefault("final_score_status", normalized.get("delivery_score_status"))
    return normalized
