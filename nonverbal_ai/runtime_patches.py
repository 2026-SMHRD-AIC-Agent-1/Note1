"""Runtime corrections for the preserved nonverbal analyzer.

The original source in `_source_parts/` is kept intact. The wrapper loads this file
after the original module so these corrected functions/constants override the
preserved source without rewriting the large original file.
"""
from __future__ import annotations

import re


# --------------------------------------------------------------------
# A!SK V1 policy confirmed 2026-09-14
# --------------------------------------------------------------------
# Visual calibration: 3 seconds of stable framing around the screen-center target.
CALIBRATION_CLIP_DURATION_SEC = 3.0
CALIBRATION_SCRIPT_TEXT = "안녕하세요. 지금부터 면접을 시작하겠습니다."

# Meaningful gaze deviation: 1 second or longer.
GAZE_EPISODE_CONFIG = EpisodeConfig(min_exceed_duration_sec=1.0, min_return_duration_sec=0.15)

# Posture is evaluated as sustained deviation, not brief natural movement.
# Head direction and body/shoulder movement therefore share a 2-second minimum.
FACE_EPISODE_CONFIG = EpisodeConfig(min_exceed_duration_sec=2.0, min_return_duration_sec=0.3)
BODY_MOVEMENT_EPISODE_CONFIG = EpisodeConfig(min_exceed_duration_sec=2.0, min_return_duration_sec=0.3)


def analyze_gaze_direction(series, calibration=None):
    """Summarize gaze without treating unmeasurable iris frames as centered.

    Iris mode excludes frames whose EAR is below MIN_EAR_FOR_GAZE_CHECK from
    gaze-ratio denominators. Head-pose approximation uses yaw, so EAR does not
    gate those frames. `gaze_valid_frame_ratio` is returned for QA/gating.

    A!SK V1 additionally requires an actual deviation episode to persist for at
    least 1 second; the global GAZE_EPISODE_CONFIG above enforces that policy.
    """
    if series.gaze_is_approx:
        source_values = series.yaw
        baseline = calibration.yaw_baseline if calibration is not None else compute_baseline(series.timestamps, source_values)
        threshold = GAZE_APPROX_YAW_THRESHOLD_DEG
        data_source = "head_pose_approx"
        valid_mask = [True] * len(source_values)
    else:
        source_values = series.gaze_ratio
        baseline = calibration.gaze_baseline if calibration is not None else compute_baseline(series.timestamps, source_values)
        threshold = GAZE_DEVIATION_RATIO_THRESHOLD
        data_source = "iris"
        valid_mask = [ear_v >= MIN_EAR_FOR_GAZE_CHECK for ear_v in series.ear]

    # Invalid iris frames are set to neutral only for episode segmentation; they
    # are excluded from the ratio denominator below.
    dev = [(v - baseline) if valid else 0.0 for v, valid in zip(source_values, valid_mask)]

    def is_dev(v):
        return abs(v) >= threshold

    episodes = detect_episodes(series.timestamps, dev, is_dev, GAZE_EPISODE_CONFIG)
    count, total_sec = summarize_episodes(episodes)

    def direction_value(e):
        v = _value_at(series.timestamps, dev, e.start_sec)
        return "right" if v >= 0 else "left"

    valid_devs = [v for v, valid in zip(dev, valid_mask) if valid]
    n_total = len(dev)
    n_valid = len(valid_devs)
    if n_valid:
        center_ratio = round(sum(1 for v in valid_devs if not is_dev(v)) / n_valid, 3)
        left_ratio = round(sum(1 for v in valid_devs if v <= -threshold) / n_valid, 3)
        right_ratio = round(sum(1 for v in valid_devs if v >= threshold) / n_valid, 3)
    else:
        center_ratio = left_ratio = right_ratio = None

    return {
        "gaze_center_ratio": center_ratio,
        "gaze_left_ratio": left_ratio,
        "gaze_right_ratio": right_ratio,
        "gaze_deviation_count": count,
        "gaze_deviation_total_sec": round(total_sec, 2),
        "gaze_valid_frame_ratio": round(n_valid / n_total, 3) if n_total else 0.0,
        "gaze_events": _episodes_to_events(episodes, EVENT_TYPE_GAZE_AWAY, value_fn=direction_value),
        "gaze_data_source": data_source,
    }


def _normalize_stt_token(token):
    m = re.search(r"[가-힣]+|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?", token)
    return m.group(0) if m else ""


def count_filler_words(stt_text, filler_words=None, word_timestamps=None, total_duration_sec=None):
    """Count internal filler tokens exactly; user-facing reports call them hesitation expressions."""
    filler_words = filler_words or DEFAULT_FILLER_WORDS
    filler_set = set(filler_words)

    if word_timestamps is None:
        tokens = re.findall(r"[가-힣]+|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?", stt_text)
        return {"filler_word_count": sum(1 for token in tokens if token in filler_set)}

    occurrences = []
    for raw_word, t in word_timestamps:
        normalized = _normalize_stt_token(raw_word)
        if normalized in filler_set:
            occurrences.append((normalized, t))
    occurrences.sort(key=lambda wt: wt[1])

    episode_count = 0
    prev_t = None
    for _word, t in occurrences:
        if prev_t is None or (t - prev_t) > FILLER_EPISODE_GAP_SEC:
            episode_count += 1
        prev_t = t

    result = {
        "filler_word_count": len(occurrences),
        "filler_episode_count": episode_count,
        "filler_timestamps": [t for _word, t in occurrences],
        "filler_events": [
            NonverbalEvent(event_type=EVENT_TYPE_FILLER_WORD, start_time_sec=round(t, 2), end_time_sec=None, value=word)
            for word, t in occurrences
        ],
    }
    result["filler_per_min"] = (
        round(len(occurrences) / (total_duration_sec / 60.0), 1)
        if total_duration_sec and total_duration_sec > 0 else None
    )
    return result


def calculate_speaking_speed(stt_text, speaking_duration_sec):
    """Keep the existing character-rate metric but exclude punctuation/whitespace."""
    if speaking_duration_sec <= 0:
        raise ValueError("speaking_duration_sec은 0보다 커야 합니다.")
    units = re.findall(r"[가-힣A-Za-z0-9]", stt_text)
    unit_count = len(units)
    return {
        "speaking_speed": round(unit_count / (speaking_duration_sec / 60.0), 1),
        "syllables_per_sec": round(unit_count / speaking_duration_sec, 2),
    }
