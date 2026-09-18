"""Report-ready delivery-stability V1 profile builder.

This module merges already-computed nonverbal/audio measurements with STT
stability features. It intentionally does NOT assign final weights, score bands,
or a 0-100 score yet. Those product decisions remain versioned separately.

Confirmed A!SK V1 policy (2026-09-14):
- Calibration is required before gaze/posture can be scored.
- Calibrated iris gaze is score-eligible; meaningful gaze deviation >= 1 sec.
- Calibrated posture is score-eligible; meaningful posture deviation >= 2 sec.
- Gaze/posture use both deviation frequency and deviation time ratio.
- Audio failure never becomes a bad score. It becomes measurement_unavailable.
- Context-dependent words such as '그', '약간' are reported only when clearly
  hesitation-like; otherwise omitted from the user report.
- User-facing terms are '머뭇거림 표현' and '반복 표현'. They are report-only,
  not score inputs.
"""
from __future__ import annotations

from typing import Any, Dict

VERSION = "delivery-stability-v1-candidate.2"


def _get(d: Dict[str, Any] | None, *keys, default=None):
    cur: Any = d or {}
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _status(available: bool, *, score_eligible: bool = False, reason: str | None = None) -> dict:
    return {
        "measurement_status": "available" if available else "measurement_unavailable",
        "score_eligible": bool(available and score_eligible),
        "reason": reason,
    }


def _fallback_speech_habits(stt_features: dict, language_analysis_allowed: bool) -> dict:
    if not language_analysis_allowed:
        return {
            "score_included": False,
            "hesitation": {"user_label": "머뭇거림 표현", "total_count": None, "items": []},
            "repetition": {"user_label": "반복 표현", "total_count": None, "items": []},
        }
    return {
        "score_included": False,
        "hesitation": {
            "user_label": "머뭇거림 표현",
            "total_count": stt_features.get("strong_filler_count"),
            "items": stt_features.get("hesitation_items") or [],
            "note": "사용자 리포트 전용이며 점수에 반영하지 않습니다.",
        },
        "repetition": {
            "user_label": "반복 표현",
            "total_count": stt_features.get("repetition_count"),
            "items": stt_features.get("repetition_items") or [],
        },
    }


def build_delivery_profile(
    raw_nonverbal: dict,
    nonverbal_features: dict,
    stt_features: dict | None = None,
) -> dict:
    """Merge one answer's STT + nonverbal measurements into a report-ready profile."""
    stt_features = stt_features or {}

    audio_status = _get(nonverbal_features, "measurement", "audio_status", default="measurement_unavailable")
    audio_available = audio_status == "available"
    audio_issue_codes = _get(nonverbal_features, "measurement", "audio_issue_codes", default=[]) or []

    # MIC_SILENT/other audio failures can create plausible-looking Whisper text.
    # Keep raw STT for audit, but do not allow it to feed scoring/report judgments.
    language_analysis_allowed = audio_available
    retake_recommended = not audio_available

    calibration_used = bool(_get(nonverbal_features, "measurement", "calibration_used", default=False))
    flow_available = audio_available and _get(nonverbal_features, "speaking_flow", "status") == "available"
    voice_available = audio_available and _get(nonverbal_features, "voice_stability", "status") == "available"

    # Pace keeps all definitions explicit until the product chooses one primary metric.
    articulation_rate = raw_nonverbal.get("speaking_speed") if audio_available else None
    timed_span_rate = stt_features.get("timed_span_syllables_per_min") if audio_available else None
    gross_rate = stt_features.get("gross_syllables_per_min") if audio_available else None
    pace_variability_cv = stt_features.get("segment_rate_cv") if audio_available else None
    pace_sample_count = stt_features.get("segment_rate_sample_count") if audio_available else None
    pace_available = any(v is not None for v in (articulation_rate, timed_span_rate, gross_rate))

    gaze_score_candidate = bool(_get(nonverbal_features, "measurement", "gaze_score_candidate", default=False))
    gaze_status = _get(nonverbal_features, "measurement", "gaze_status", default="source_unknown")
    gaze_available = gaze_status not in (None, "source_unknown")

    posture_score_candidate = bool(_get(nonverbal_features, "measurement", "posture_score_candidate", default=False))
    posture_status = _get(nonverbal_features, "head_posture_stability", "status", default="reference_only_uncalibrated")
    posture_values = (
        _get(nonverbal_features, "head_posture_stability", "face_deviation_per_min_reference"),
        _get(nonverbal_features, "head_posture_stability", "face_deviation_time_ratio_reference"),
        _get(nonverbal_features, "head_posture_stability", "body_movement_per_min_reference"),
        _get(nonverbal_features, "head_posture_stability", "body_movement_time_ratio_reference"),
    )
    posture_available = any(value is not None for value in posture_values)

    speech_habits = stt_features.get("speech_habits_report")
    if not isinstance(speech_habits, dict):
        speech_habits = _fallback_speech_habits(stt_features, language_analysis_allowed)
    if not language_analysis_allowed:
        speech_habits = _fallback_speech_habits(stt_features, False)

    gaze_component = {
        **_status(gaze_available, score_eligible=gaze_score_candidate, reason=None if gaze_score_candidate else "successful iris calibration required"),
        "gaze_status": gaze_status,
        "gaze_valid_frame_ratio": _get(nonverbal_features, "measurement", "gaze_valid_frame_ratio"),
        "center_ratio": _get(nonverbal_features, "gaze_stability", "center_ratio") if gaze_score_candidate else None,
        "deviation_per_min": _get(nonverbal_features, "gaze_stability", "deviation_per_min") if gaze_score_candidate else None,
        "deviation_time_ratio": _get(nonverbal_features, "gaze_stability", "deviation_time_ratio") if gaze_score_candidate else None,
        "meaningful_deviation_min_sec": 1.0,
        "reference": {
            "iris_center_ratio": _get(nonverbal_features, "gaze_stability", "iris_center_ratio_reference"),
            "iris_deviation_per_min": _get(nonverbal_features, "gaze_stability", "iris_deviation_per_min_reference"),
            "head_pose_deviation_per_min": _get(nonverbal_features, "gaze_stability", "approx_deviation_per_min"),
        },
    }

    posture_component = {
        **_status(
            posture_available,
            score_eligible=posture_score_candidate,
            reason=None if posture_score_candidate else "successful calibration required",
        ),
        "status": posture_status,
        "signals": ["head_direction", "shoulder_tilt", "upper_body_position"],
        "face_deviation_per_min": _get(nonverbal_features, "head_posture_stability", "face_deviation_per_min") if posture_score_candidate else None,
        "face_deviation_time_ratio": _get(nonverbal_features, "head_posture_stability", "face_deviation_time_ratio") if posture_score_candidate else None,
        "body_movement_per_min": _get(nonverbal_features, "head_posture_stability", "body_movement_per_min") if posture_score_candidate else None,
        "body_movement_time_ratio": _get(nonverbal_features, "head_posture_stability", "body_movement_time_ratio") if posture_score_candidate else None,
        "meaningful_deviation_min_sec": 2.0,
        "reference": {
            "face_deviation_per_min": posture_values[0],
            "face_deviation_time_ratio": posture_values[1],
            "body_movement_per_min": posture_values[2],
            "body_movement_time_ratio": posture_values[3],
        },
    }

    return {
        "version": VERSION,
        "final_score": None,
        "final_score_status": "policy_pending",
        "measurement": {
            "audio_status": audio_status,
            "audio_issue_codes": audio_issue_codes,
            "language_analysis_allowed": language_analysis_allowed,
            "retake_recommended": retake_recommended,
            "calibration_used": calibration_used,
            "calibration_required_for_visual_score": True,
        },
        "components": {
            "speaking_flow": {
                **_status(flow_available, score_eligible=flow_available, reason=None if flow_available else "audio unavailable"),
                "pause_ratio": _get(nonverbal_features, "speaking_flow", "pause_ratio") if flow_available else None,
                "pause_per_min": _get(nonverbal_features, "speaking_flow", "pause_per_min") if flow_available else None,
                "avg_pause_sec": _get(nonverbal_features, "speaking_flow", "avg_pause_sec") if flow_available else None,
                "max_pause_sec": _get(nonverbal_features, "speaking_flow", "max_pause_sec") if flow_available else None,
                "long_pause_per_min": _get(nonverbal_features, "speaking_flow", "long_pause_per_min") if flow_available else None,
                "scoring_rule": "threshold_pending; pauses are not a linear penalty",
            },
            "pace_stability": {
                **_status(pace_available, score_eligible=pace_available, reason=None if pace_available else "audio/STT pace unavailable"),
                "articulation_rate_units_per_min": articulation_rate,
                "timed_span_hangul_syllables_per_min": timed_span_rate,
                "gross_hangul_syllables_per_min": gross_rate,
                "segment_rate_cv": pace_variability_cv,
                "segment_rate_sample_count": pace_sample_count,
                "primary_rate_metric": None,
                "primary_rate_metric_status": "product_decision_pending",
            },
            "volume_stability": {
                **_status(voice_available, score_eligible=voice_available, reason=None if voice_available else "audio unavailable"),
                "volume_variation_db": _get(nonverbal_features, "voice_stability", "volume_variation_db") if voice_available else None,
                "average_volume_db_reference": _get(nonverbal_features, "voice_stability", "average_volume_db_reference") if voice_available else None,
                "scoring_rule": "use within-answer variation; calibration/base loudness is report reference only",
            },
            "gaze_stability": gaze_component,
            "posture_stability": posture_component,
            # Backward-compatible key retained for any existing consumer.
            "head_posture_stability": posture_component,
        },
        "report_only": {
            "speech_habits": speech_habits,
            "blink_per_min": _get(nonverbal_features, "descriptive_only", "blink_per_min"),
            "smile_episode_count": _get(nonverbal_features, "descriptive_only", "smile_episode_count"),
            "expression_change_count": _get(nonverbal_features, "descriptive_only", "expression_change_count"),
            "nod_count": _get(nonverbal_features, "descriptive_only", "nod_count"),
            "gesture_per_min": _get(nonverbal_features, "descriptive_only", "gesture_per_min"),
        },
        "aggregation_policy": {
            "score_each_question": True,
            "session_summary": "mean_of_questions",
            "mid_interview_recalibration": False,
            "technical_faults_are_measurement_errors": True,
        },
        "pending_product_decisions": [
            "final component weights and 0-100 normalization",
            "primary pace metric: articulation rate vs pause-inclusive speech rate",
            "production thresholds/bands for flow, pace, volume, calibrated gaze and calibrated posture",
        ],
    }
