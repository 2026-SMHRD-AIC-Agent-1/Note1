"""Score-ready feature extraction for A!SK delivery-stability calibration.

This module does not assign a final score or psychological label. It converts raw
nonverbal output into normalized measurements plus measurement-status flags so
thresholds can be calibrated separately from the 45-video pilot set.
"""
from __future__ import annotations


def _rate_per_min(count, duration_sec):
    if count is None or not duration_sec or duration_sec <= 0:
        return None
    return round(float(count) / (float(duration_sec) / 60.0), 3)


def _time_ratio(seconds, duration_sec):
    if seconds is None or not duration_sec or duration_sec <= 0:
        return None
    return round(float(seconds) / float(duration_sec), 4)


def infer_duration_sec(raw):
    """Best-effort fallback for historical JSON that omitted duration."""
    pause_ratio = raw.get("pause_ratio")
    total_pause_sec = raw.get("total_pause_sec")
    if pause_ratio not in (None, 0) and total_pause_sec is not None:
        return round(float(total_pause_sec) / float(pause_ratio), 3)
    blink_per_min = raw.get("blink_per_min")
    blink_count = raw.get("blink_count_total")
    if blink_per_min not in (None, 0) and blink_count is not None:
        return round(float(blink_count) / float(blink_per_min) * 60.0, 3)
    return None


def derive_stability_features(raw, duration_sec=None):
    """Convert one raw analyzer result into calibration-ready stability features.

    Rules from the 45-video review:
    - Only calibrated iris gaze may become a future score input.
      Uncalibrated iris and head-pose gaze remain reference-only.
    - Head/posture uses deviation frequency/time, not absolute yaw/pitch/roll.
    - Pauses are evidence, not an automatic penalty; STT context is required.
    - Voice stability uses within-answer dB variation, not average loudness.
    - Blink/smile/expression/nod/shake/gesture/pitch remain descriptive only.
    - Audio failure means measurement unavailable, never a zero performance score.
    """
    duration_sec = duration_sec or infer_duration_sec(raw)

    audio_quality = raw.get("audio_quality") or {}
    audio_valid = bool(audio_quality.get("is_valid", True))
    audio_issues = [x.get("code") for x in audio_quality.get("issues", []) if isinstance(x, dict)]

    calibration_used = bool(raw.get("calibration_used", False))
    gaze_source = raw.get("gaze_data_source")
    if gaze_source == "iris" and calibration_used:
        gaze_status = "measured_iris_calibrated"
        gaze_score_candidate = True
    elif gaze_source == "iris":
        gaze_status = "measured_iris_uncalibrated"
        gaze_score_candidate = False
    elif gaze_source == "head_pose_approx":
        gaze_status = "approx_head_pose"
        gaze_score_candidate = False
    else:
        gaze_status = "source_unknown"
        gaze_score_candidate = False

    iris_reference = gaze_source == "iris"
    flow_available = audio_valid and raw.get("pause_count") is not None
    voice_available = audio_valid and raw.get("db_std") is not None

    return {
        "measurement": {
            "duration_sec": duration_sec,
            "calibration_used": calibration_used,
            "audio_status": "available" if audio_valid else "measurement_unavailable",
            "audio_issue_codes": audio_issues,
            "gaze_status": gaze_status,
            "gaze_score_candidate": gaze_score_candidate,
            "gaze_valid_frame_ratio": raw.get("gaze_valid_frame_ratio"),
        },
        "gaze_stability": {
            # Candidate fields stay empty until an iris baseline was actually calibrated.
            "center_ratio": raw.get("gaze_center_ratio") if gaze_score_candidate else None,
            "deviation_per_min": _rate_per_min(raw.get("gaze_deviation_count"), duration_sec) if gaze_score_candidate else None,
            "deviation_time_ratio": _time_ratio(raw.get("gaze_deviation_total_sec"), duration_sec) if gaze_score_candidate else None,
            # Keep uncalibrated iris/head-pose values for pilot review without treating them as scores.
            "iris_center_ratio_reference": raw.get("gaze_center_ratio") if iris_reference else None,
            "iris_deviation_per_min_reference": _rate_per_min(raw.get("gaze_deviation_count"), duration_sec) if iris_reference else None,
            "iris_deviation_time_ratio_reference": _time_ratio(raw.get("gaze_deviation_total_sec"), duration_sec) if iris_reference else None,
            "approx_deviation_per_min": _rate_per_min(raw.get("gaze_deviation_count"), duration_sec) if gaze_source == "head_pose_approx" else None,
            "approx_deviation_time_ratio": _time_ratio(raw.get("gaze_deviation_total_sec"), duration_sec) if gaze_source == "head_pose_approx" else None,
            "scoring_note": "Only calibrated iris gaze is score-eligible; other gaze values are reference-only.",
        },
        "head_posture_stability": {
            "status": "calibrated_candidate" if calibration_used else "reference_only_uncalibrated",
            "face_deviation_per_min": _rate_per_min(raw.get("face_deviation_count"), duration_sec),
            "face_deviation_time_ratio": _time_ratio(raw.get("face_deviation_total_sec"), duration_sec),
            "body_movement_per_min_reference": _rate_per_min(raw.get("body_movement_count"), duration_sec),
            "body_movement_time_ratio_reference": _time_ratio(raw.get("body_movement_total_sec"), duration_sec),
            "scoring_note": "45-video pilot was uncalibrated and posture/body events were sparse; do not score these values yet.",
        },
        "speaking_flow": {
            "status": "available" if flow_available else "measurement_unavailable",
            "pause_per_min": _rate_per_min(raw.get("pause_count"), duration_sec) if flow_available else None,
            "pause_ratio": raw.get("pause_ratio") if flow_available else None,
            "avg_pause_sec": raw.get("avg_pause_sec") if flow_available else None,
            "max_pause_sec": raw.get("max_pause_sec") if flow_available else None,
            "long_pause_per_min": _rate_per_min(raw.get("long_pause_count"), duration_sec) if flow_available else None,
            "scoring_note": "STT context required; pauses are not a linear penalty.",
        },
        "voice_stability": {
            "status": "available" if voice_available else "measurement_unavailable",
            "volume_variation_db": raw.get("db_std") if voice_available else None,
            "average_volume_db_reference": raw.get("mean_db") if voice_available else None,
            "pitch_variation_reference": raw.get("f0_std") if voice_available else None,
        },
        "descriptive_only": {
            "blink_per_min": raw.get("blink_per_min"),
            "long_blink_count": raw.get("long_blink_count"),
            "smile_episode_count": raw.get("smile_episode_count"),
            "expression_change_count": raw.get("expression_change_count"),
            "nod_count": raw.get("nod_count"),
            "shake_count": raw.get("shake_count"),
            "gesture_per_min": raw.get("gesture_per_min"),
        },
    }
