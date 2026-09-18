"""전달 안정성(delivery_score) 최종 점수 계산.

PM 확정 (2026-09, 리뷰 반영):
    - 5개 항목 가중치: gaze_stability 20% / posture_stability 15% /
      speaking_flow 30% / pace_stability 20% / volume_stability 15%
    - 시선 점수 = 이탈 시간비율 점수 * 60% + 이탈 빈도 점수 * 40%
    - 자세 점수 = 이탈 시간비율 점수 * 60% + 이탈 빈도 점수 * 40%
    - 말하기 흐름 점수 = 전체 침묵비율 점수 * 50% + 긴 침묵 빈도 점수 * 30%
      + 가장 긴 침묵 점수 * 20%
    - 발화 속도 점수 = 적정 속도 범위 점수 * 60% + 구간별 속도 변화 안정성 점수 * 40%
    - 음량 점수 = 답변 중 음량 변화 안정성만 사용 (평균 음량 절대값은 참고용, 점수 미반영)
    - 5개 항목 중 하나라도 측정 불가(measurement_unavailable /
      score_eligible=False)면 "나머지 항목만으로 평균"하지 않고 전체를
      측정 불가로 처리하고 재녹화를 안내한다.

아직 팀에서 확정하지 않은 것 (MVP 기본값 — 아래 상수만 바꾸면 조정 가능):
    - 각 세부 raw 값 -> 0~100 환산 임계값 (예: 침묵비율 몇 %면 몇 점인지)

입력은 nonverbal_ai.delivery_stability_v1.build_delivery_profile()이 만든
delivery_profile(components.*)을 그대로 사용한다 (integration_contract_v1의
normalize_delivery_profile을 거친 형태).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

VERSION = "delivery-scoring-mvp-v2"

# ------------------------------------------------------------------
# PM 확정: 5개 항목 가중치 (합계 100%)
# ------------------------------------------------------------------
COMPONENT_WEIGHTS = {
    "gaze_stability": 0.20,
    "posture_stability": 0.15,
    "speaking_flow": 0.30,
    "pace_stability": 0.20,
    "volume_stability": 0.15,
}

# PM 확정: 시선/자세 세부 서브가중치
DEVIATION_SUBWEIGHTS = {"time_ratio": 0.6, "frequency": 0.4}

# PM 확정: 말하기 흐름 세부 서브가중치 (전체 침묵비율/긴 침묵 빈도/최장 침묵)
SPEAKING_FLOW_SUBWEIGHTS = {"pause_ratio": 0.5, "long_pause_freq": 0.3, "max_pause": 0.2}

# PM 확정: 발화 속도 세부 서브가중치 (적정 범위/구간별 변화 안정성)
PACE_SUBWEIGHTS = {"target_range": 0.6, "variability": 0.4}

# ------------------------------------------------------------------
# MVP 임시 정규화 기준값 (팀 논의 후 숫자만 조정하면 됨)
# "이 값 이상이면 0점" 기준의 선형 감점 방식.
# ------------------------------------------------------------------
GAZE_TIME_RATIO_ZERO_AT = 0.30      # 이탈 시간비율 30% 이상 -> 0점
GAZE_FREQ_ZERO_AT = 6.0             # 분당 이탈 6회 이상 -> 0점

POSTURE_TIME_RATIO_ZERO_AT = 0.30
POSTURE_FREQ_ZERO_AT = 6.0          # 얼굴+상체 이탈 합산 기준

PAUSE_RATIO_ZERO_AT = 0.35          # 전체 침묵 비율 35% 이상 -> 0점
LONG_PAUSE_FREQ_ZERO_AT = 6.0       # 분당 긴 침묵 6회 이상 -> 0점
MAX_PAUSE_ZERO_AT = 8.0             # 가장 긴 침묵 8초 이상 -> 0점

PACE_TARGET_RANGE = (180.0, 320.0)  # 적정 발화속도 구간(음절/분), 팀 확정 전 임시값
PACE_ZERO_DEVIATION = 150.0         # 적정 구간에서 150 이상 벗어나면 0점
PACE_CV_ZERO_AT = 0.5               # 구간별 속도 변동계수(CV) 0.5 이상 -> 0점

VOLUME_VARIATION_ZERO_AT = 12.0     # 답변 중 음량 변동폭(dB) 12 이상 -> 0점


def _linear_score(value: Optional[float], zero_at: float, full_at: float = 0.0) -> Optional[float]:
    """value == full_at이면 100점, zero_at 이상이면 0점, 사이는 선형 감점."""
    if value is None:
        return None
    if zero_at == full_at:
        return 100.0
    ratio = (value - full_at) / (zero_at - full_at)
    ratio = max(0.0, min(1.0, ratio))
    return round((1.0 - ratio) * 100, 1)


def _get(component: Dict[str, Any], key: str):
    return (component or {}).get(key)


def score_gaze(component: Dict[str, Any]) -> Optional[float]:
    if not (component or {}).get("score_eligible"):
        return None
    time_score = _linear_score(_get(component, "deviation_time_ratio"), GAZE_TIME_RATIO_ZERO_AT)
    freq_score = _linear_score(_get(component, "deviation_per_min"), GAZE_FREQ_ZERO_AT)
    if time_score is None or freq_score is None:
        return None
    return round(
        time_score * DEVIATION_SUBWEIGHTS["time_ratio"] + freq_score * DEVIATION_SUBWEIGHTS["frequency"], 1
    )


def score_posture(component: Dict[str, Any]) -> Optional[float]:
    if not (component or {}).get("score_eligible"):
        return None
    time_ratio = _get(component, "face_deviation_time_ratio")
    face_freq = _get(component, "face_deviation_per_min")
    body_freq = _get(component, "body_movement_per_min")
    if face_freq is None and body_freq is None:
        combined_freq = None
    else:
        combined_freq = (face_freq or 0.0) + (body_freq or 0.0)
    time_score = _linear_score(time_ratio, POSTURE_TIME_RATIO_ZERO_AT)
    freq_score = _linear_score(combined_freq, POSTURE_FREQ_ZERO_AT)
    if time_score is None or freq_score is None:
        return None
    return round(
        time_score * DEVIATION_SUBWEIGHTS["time_ratio"] + freq_score * DEVIATION_SUBWEIGHTS["frequency"], 1
    )


def score_speaking_flow(component: Dict[str, Any]) -> Optional[float]:
    if not (component or {}).get("score_eligible"):
        return None
    ratio_score = _linear_score(_get(component, "pause_ratio"), PAUSE_RATIO_ZERO_AT)
    long_freq_score = _linear_score(_get(component, "long_pause_per_min"), LONG_PAUSE_FREQ_ZERO_AT)
    max_pause_score = _linear_score(_get(component, "max_pause_sec"), MAX_PAUSE_ZERO_AT)
    if ratio_score is None or long_freq_score is None or max_pause_score is None:
        return None
    return round(
        ratio_score * SPEAKING_FLOW_SUBWEIGHTS["pause_ratio"]
        + long_freq_score * SPEAKING_FLOW_SUBWEIGHTS["long_pause_freq"]
        + max_pause_score * SPEAKING_FLOW_SUBWEIGHTS["max_pause"],
        1,
    )


def score_pace(component: Dict[str, Any]) -> Optional[float]:
    if not (component or {}).get("score_eligible"):
        return None
    rate = (
        _get(component, "timed_span_hangul_syllables_per_min")
        or _get(component, "gross_hangul_syllables_per_min")
        or _get(component, "articulation_rate_units_per_min")
    )
    cv = _get(component, "segment_rate_cv")
    if rate is None or cv is None:
        return None

    low, high = PACE_TARGET_RANGE
    if low <= rate <= high:
        deviation = 0.0
    elif rate < low:
        deviation = low - rate
    else:
        deviation = rate - high
    range_score = _linear_score(deviation, PACE_ZERO_DEVIATION, full_at=0.0)
    variability_score = _linear_score(cv, PACE_CV_ZERO_AT)
    if range_score is None or variability_score is None:
        return None
    return round(
        range_score * PACE_SUBWEIGHTS["target_range"] + variability_score * PACE_SUBWEIGHTS["variability"], 1
    )


def score_volume(component: Dict[str, Any]) -> Optional[float]:
    if not (component or {}).get("score_eligible"):
        return None
    return _linear_score(_get(component, "volume_variation_db"), VOLUME_VARIATION_ZERO_AT)


_SCORERS = {
    "gaze_stability": score_gaze,
    "posture_stability": score_posture,
    "speaking_flow": score_speaking_flow,
    "pace_stability": score_pace,
    "volume_stability": score_volume,
}

_COMPONENT_LABELS_KO = {
    "gaze_stability": "시선 안정성",
    "posture_stability": "자세 안정성",
    "speaking_flow": "말하기 흐름",
    "pace_stability": "발화 속도",
    "volume_stability": "음량 안정성",
}


def compute_delivery_score(delivery_profile: Dict[str, Any] | None) -> Dict[str, Any]:
    """delivery_profile을 받아 전달 안정성 최종 점수를 계산한다.

    5개 항목 중 하나라도 계산 불가면 부분 평균을 내지 않고 전체를
    measurement_unavailable로 처리해 재녹화를 안내한다.
    """
    if not delivery_profile:
        return {
            "version": VERSION,
            "delivery_score": None,
            "status": "measurement_unavailable",
            "missing_components": list(COMPONENT_WEIGHTS.keys()),
            "component_scores": {},
            "message": "전달 분석 결과가 없어 전달 안정성 점수를 계산할 수 없습니다. 다시 녹화해주세요.",
        }

    components = delivery_profile.get("components") or {}

    sub_scores: Dict[str, Optional[float]] = {}
    missing: list[str] = []
    for key, scorer in _SCORERS.items():
        value = scorer(components.get(key, {}))
        sub_scores[key] = value
        if value is None:
            missing.append(key)

    if missing:
        missing_labels = ", ".join(_COMPONENT_LABELS_KO.get(k, k) for k in missing)
        return {
            "version": VERSION,
            "delivery_score": None,
            "status": "measurement_unavailable",
            "missing_components": missing,
            "component_scores": sub_scores,
            "message": f"다음 항목을 측정하지 못해 전달 안정성 점수를 계산할 수 없습니다: {missing_labels}. 다시 녹화해주세요.",
        }

    total = sum(sub_scores[k] * w for k, w in COMPONENT_WEIGHTS.items())
    return {
        "version": VERSION,
        "delivery_score": round(total, 1),
        "status": "available",
        "missing_components": [],
        "component_scores": sub_scores,
        "message": None,
    }
