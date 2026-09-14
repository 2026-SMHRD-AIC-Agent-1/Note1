"""Report-ready delivery-stability V1 profile builder.

This module merges the already-computed nonverbal/audio measurements with STT
stability features. It intentionally does NOT assign final weights, thresholds,
or a 0-100 score yet. Those are product/policy decisions that must be fixed
separately and versioned.

Important rules from the 45-video pilot:
- Audio failure never becomes a bad score. It becomes measurement_unavailable.
- If audio is unusable, STT text may be hallucinated and must not be used for
  language scoring or delivery scoring.
- Pause is measured primarily from the audio signal; Whisper word gaps are only
  auxiliary evidence.
- Context fillers such as '그', '약간' are report-only unless context shows a
  real disfluency.
- Uncalibrated iris/head-pose gaze is reference-only. Only calibrated iris may
  become a future score input.
- Posture/body movement remains reference-only until calibrated validation.
"""
from __future__ import annotations

from typing import Any, Dict

VERSION = "delivery-stability-v1-candidate"


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


def build_delivery_profile(
    raw_nonverbal: dict,
    nonverbal_features: dict,
    stt_features: dict | None = None,
) -> dict:
    """Merge one answer's STT + nonverbal measurements into a report-ready profile.

    The return value is safe to expose to later scoring/report code because it
    keeps score eligibility separate from raw measurement availability.
    """
    stt_features = stt_features or {}

    audio_status = _get(nonverbal_features, "measurement", "audio_status", default="measurement_unavailable")
    audio_available = audio_status == "available"
    audio_issue_codes = _get(nonverbal_features, "measurement", "audio_issue_codes", default=[]) or []

    # MIC_SILENT/other audio failures can create plausible-looking Whisper text.
    # Preserve the raw STT elsewhere for audit, but do not allow it to feed scoring.
    language_analysis_allowed = audio_available
    retake_recommended = not audio_available

    flow_available = audio_available and _get(nonverbal_features, "speaking_flow", "status") == "available"
    voice_available = audio_available and _get(nonverbal_features, "voice_stability", "status") == "available"

    # Pace deliberately exposes both concepts instead of silently choosing one:
    # - articulation rate: pause-excluded audio/STT combined rate from nonverbal analyzer
    # - speech rate: STT span/gross rate including natural pauses
    # Product must decide which becomes the score's primary pace metric.
    articulation_rate = raw_nonverbal.get("speaking_speed") if audio_available else None
    timed_span_rate = stt_features.get("timed_span_syllables_per_min") if audio_available else None
    gross_rate = stt_features.get("gross_syllables_per_min") if audio_available else None
    pace_variability_cv = stt_features.get("segment_rate_cv") if audio_available else None
    pace_sample_count = stt_features.get("segment_rate_sample_count") if audio_available else None
    pace_available = any(v is not None for v in (articulation_rate, timed_span_rate, gross_rate))

    gaze_score_candidate = bool(_get(nonverbal_features, "measurement", "gaze_score_candidate", default=False))
    gaze_status = _get(nonverbal_features, "measurement", "gaze_status", default="source_unknown")
    gaze_available = gaze_status not in (None, "source_unknown")

    posture_status = _get(nonverbal_features, "head_posture_stability", "status", default="reference_only_uncalibrated")
    posture_score_candidate = posture_status == "calibrated_candidate"

    strong_fillers = stt_features.get("strong_filler_count") if language_analysis_allowed else None
    context_fillers = stt_features.get("context_filler_count") if language_analysis_allowed else None
    repetitions = stt_features.get("repetition_count") if language_analysis_allowed else None

    return {
        "version": VERSION,
        "final_score": None,
        "final_score_status": "policy_pending",
        "measurement": {
            "audio_status": audio_status,
            "audio_issue_codes": audio_issue_codes,
            "language_analysis_allowed": language_analysis_allowed,
            "retake_recommended": retake_recommended,
            "calibration_used": bool(_get(nonverbal_features, "measurement", "calibration_used", default=False)),
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
                "scoring_rule": "use within-answer variation; absolute loudness is reference-only",
            },
            "gaze_stability": {
                **_status(gaze_available, score_eligible=gaze_score_candidate, reason=None if gaze_score_candidate else "calibrated iris required"),
                "gaze_status": gaze_status,
                "gaze_valid_frame_ratio": _get(nonverbal_features, "measurement", "gaze_valid_frame_ratio"),
                "center_ratio": _get(nonverbal_features, "gaze_stability", "center_ratio") if gaze_score_candidate else None,
                "deviation_per_min": _get(nonverbal_features, "gaze_stability", "deviation_per_min") if gaze_score_candidate else None,
                "reference": {
                    "iris_center_ratio": _get(nonverbal_features, "gaze_stability", "iris_center_ratio_reference"),
                    "iris_deviation_per_min": _get(nonverbal_features, "gaze_stability", "iris_deviation_per_min_reference"),
                    "head_pose_deviation_per_min": _get(nonverbal_features, "gaze_stability", "approx_deviation_per_min"),
                },
            },
            "head_posture_stability": {
                **_status(True, score_eligible=posture_score_candidate, reason=None if posture_score_candidate else "calibrated validation required"),
                "status": posture_status,
                "face_deviation_per_min_reference": _get(nonverbal_features, "head_posture_stability", "face_deviation_per_min"),
                "face_deviation_time_ratio_reference": _get(nonverbal_features, "head_posture_stability", "face_deviation_time_ratio"),
                "body_movement_per_min_reference": _get(nonverbal_features, "head_posture_stability", "body_movement_per_min_reference"),
            },
        },
        "report_only": {
            "strong_filler_count": strong_fillers,
            "context_filler_count": context_fillers,
            "repetition_count": repetitions,
            "filler_note": "Strong/context fillers are separated. Context fillers are not automatic penalties.",
            "blink_per_min": _get(nonverbal_features, "descriptive_only", "blink_per_min"),
            "smile_episode_count": _get(nonverbal_features, "descriptive_only", "smile_episode_count"),
            "expression_change_count": _get(nonverbal_features, "descriptive_only", "expression_change_count"),
            "nod_count": _get(nonverbal_features, "descriptive_only", "nod_count"),
            "gesture_per_min": _get(nonverbal_features, "descriptive_only", "gesture_per_min"),
        },
        "pending_product_decisions": [
            "final component weights and 0-100 normalization",
            "primary pace metric: articulation rate vs pause-inclusive speech rate",
            "production thresholds/bands for flow, pace and volume",
            "whether calibrated gaze enters V1 score or remains report-only",
        ],
    }
