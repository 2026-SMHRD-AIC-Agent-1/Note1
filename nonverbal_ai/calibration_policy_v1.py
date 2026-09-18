"""A!SK calibration / nonverbal evaluation V1 product policy.

This file centralizes the PM-confirmed rules so local validation, backend wiring,
and frontend UX can share the same contract without hiding product decisions in
scoring code.
"""

VERSION = "aisk-calibration-nonverbal-v1"

# Session gate
CALIBRATION_REQUIRED = True
CALIBRATION_HARD_GATE = True
MID_INTERVIEW_RECALIBRATION = False

# Stage 1: visual calibration
VISUAL_STABLE_DURATION_SEC = 3.0
VISUAL_TARGET = "screen_center"
VISUAL_REQUIRED_PARTS = ("full_face", "both_eyes", "both_shoulders")
REALTIME_GUIDANCE_REQUIRED = True

# Stage 2: audio environment check
AUDIO_SCRIPT_TEXT = "안녕하세요. 지금부터 면접을 시작하겠습니다."
AUDIO_ENVIRONMENT_ONLY = True
SAVE_BASE_VOLUME = True
BASE_VOLUME_DIRECT_SCORE = False
CALIBRATION_PITCH_SCORE = False
CALIBRATION_READING_SPEED_SCORE = False

# Nonverbal episode policy after successful calibration
GAZE_DEVIATION_MIN_SEC = 1.0
POSTURE_DEVIATION_MIN_SEC = 2.0
GAZE_SCORE_USES = ("deviation_count", "deviation_time_ratio")
POSTURE_SCORE_USES = ("deviation_count", "deviation_time_ratio")
POSTURE_SIGNALS = ("head_direction", "shoulder_tilt", "upper_body_position")
PER_QUESTION_SCORING = True
SESSION_AGGREGATION = "mean_of_questions"

# Technical fault policy
TECHNICAL_FAULT_IS_NOT_USER_BEHAVIOR = True
USER_LEAVES_FRAME_IS_BEHAVIOR = True

# User-facing speech-habit report policy
USER_LABEL_HESITATION = "머뭇거림 표현"
USER_LABEL_REPETITION = "반복 표현"
HESITATION_SCORE_INCLUDED = False
REPETITION_SCORE_INCLUDED = False
SHOW_EXPRESSION_COUNTS = True
SHOW_EXPRESSION_TIMESTAMPS = True
CONTEXT_FILLERS_REPORT_ONLY_WHEN_CONFIRMED = True


def as_dict() -> dict:
    """Serializable policy summary for API/report metadata."""
    return {
        "version": VERSION,
        "calibration": {
            "required": CALIBRATION_REQUIRED,
            "hard_gate": CALIBRATION_HARD_GATE,
            "visual_stable_duration_sec": VISUAL_STABLE_DURATION_SEC,
            "visual_target": VISUAL_TARGET,
            "visual_required_parts": list(VISUAL_REQUIRED_PARTS),
            "realtime_guidance_required": REALTIME_GUIDANCE_REQUIRED,
            "audio_script_text": AUDIO_SCRIPT_TEXT,
            "audio_environment_only": AUDIO_ENVIRONMENT_ONLY,
            "save_base_volume": SAVE_BASE_VOLUME,
            "base_volume_direct_score": BASE_VOLUME_DIRECT_SCORE,
            "mid_interview_recalibration": MID_INTERVIEW_RECALIBRATION,
        },
        "nonverbal": {
            "gaze_deviation_min_sec": GAZE_DEVIATION_MIN_SEC,
            "posture_deviation_min_sec": POSTURE_DEVIATION_MIN_SEC,
            "gaze_score_uses": list(GAZE_SCORE_USES),
            "posture_score_uses": list(POSTURE_SCORE_USES),
            "posture_signals": list(POSTURE_SIGNALS),
            "per_question_scoring": PER_QUESTION_SCORING,
            "session_aggregation": SESSION_AGGREGATION,
        },
        "speech_habits": {
            "hesitation_label": USER_LABEL_HESITATION,
            "repetition_label": USER_LABEL_REPETITION,
            "hesitation_score_included": HESITATION_SCORE_INCLUDED,
            "repetition_score_included": REPETITION_SCORE_INCLUDED,
            "show_counts": SHOW_EXPRESSION_COUNTS,
            "show_timestamps": SHOW_EXPRESSION_TIMESTAMPS,
            "context_fillers_report_only_when_confirmed": CONTEXT_FILLERS_REPORT_ONLY_WHEN_CONFIRMED,
        },
    }
