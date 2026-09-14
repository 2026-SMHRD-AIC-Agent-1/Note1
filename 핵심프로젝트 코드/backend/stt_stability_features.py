"""STT 상세 결과에서 전달 안정성용 관찰 지표를 계산한다.

이 모듈은 점수를 만들지 않는다. 45개 파일럿 검증용 raw feature와
사용자 리포트용 '머뭇거림 표현/반복 표현' 정보를 계산한다.
입력은 stt_service.transcribe_audio_detailed()의 dict와 호환된다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean, pstdev
from typing import Any

HANGUL_RE = re.compile(r"[가-힣]")
TRIM_RE = re.compile(r"^[^0-9A-Za-z가-힣]+|[^0-9A-Za-z가-힣]+$")

# 내부 개발 용어로는 filler를 유지하지만, 사용자 화면에서는 '머뭇거림 표현'으로 표시한다.
STRONG_FILLERS = {"어", "음", "저기", "그니까", "뭐랄까"}
CONTEXT_FILLERS = {"그", "약간"}

# 문맥형 표현은 오탐을 줄이기 위해 앞/뒤 모두 뚜렷한 간격이 있을 때만
# '확실한 머뭇거림'으로 리포트한다. 애매하면 후보로만 보존하고 사용자 리포트에서는 제외한다.
CONTEXT_FILLER_CONFIRM_GAP_SEC = 0.5

# Whisper가 문장 끝의 "이상입니다" 같은 짧은 구간을 별도 segment로 만들 수 있다.
# 이런 0.x초짜리 segment는 분당 속도 환산 시 수백 음절/분으로 튀어 변동성을 왜곡한다.
# 파일럿에서는 최소 2초 + 한글 8음절 이상 segment만 속도 변동 계산에 사용한다.
MIN_SEGMENT_DURATION_SEC = 2.0
MIN_SEGMENT_HANGUL_SYLLABLES = 8


def _value(item: Any, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def normalize_word(word: str) -> str:
    return TRIM_RE.sub("", (word or "").strip())


def count_hangul_syllables(text: str) -> int:
    """완성형 한글 음절만 센다. 문장부호/숫자/영문은 제외한다."""
    return len(HANGUL_RE.findall(text or ""))


def _safe_rate(count: int, seconds: float | None) -> float | None:
    if not seconds or seconds <= 0:
        return None
    return count / (seconds / 60.0)


def _round_or_none(value, digits=2):
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return round(float(value), digits)
    return None


def analyze_stt_stability(detail: dict) -> dict:
    text = detail.get("text", "") or ""
    duration = detail.get("duration_sec")
    words_raw = detail.get("words") or []
    segments_raw = detail.get("segments") or []

    words = []
    for item in words_raw:
        raw = str(_value(item, "word", "") or "")
        norm = normalize_word(raw)
        start = _value(item, "start")
        end = _value(item, "end")
        words.append({"raw": raw, "word": norm, "start": start, "end": end})

    # 시간 정보가 있는 단어를 시간순으로 정리한다.
    timed_words = [
        w for w in words
        if isinstance(w["start"], (int, float)) and isinstance(w["end"], (int, float))
    ]
    timed_words.sort(key=lambda x: (x["start"], x["end"]))

    # 단어 사이 gap. Whisper timestamp 특성상 실제 침묵을 단어 duration 안에 흡수하는 경우가 있어
    # 이 값은 보조 지표로만 사용하고, 침묵의 주 측정은 음성 신호 기반 분석을 사용한다.
    gaps = []
    for prev, cur in zip(timed_words, timed_words[1:]):
        gap = float(cur["start"]) - float(prev["end"])
        if gap >= 0:
            gaps.append(gap)

    pause_05 = [g for g in gaps if g >= 0.5]
    pause_10 = [g for g in gaps if g >= 1.0]

    # -----------------------------------------------------------------
    # 사용자 리포트용 '머뭇거림 표현'
    # -----------------------------------------------------------------
    strong_filler_items = [w for w in timed_words if w["word"] in STRONG_FILLERS]
    context_filler_items = [w for w in timed_words if w["word"] in CONTEXT_FILLERS]

    hesitation_items = []
    for w in strong_filler_items:
        hesitation_items.append({
            "expression": w["word"],
            "start_sec": _round_or_none(w["start"]),
            "kind": "clear_hesitation",
        })

    # '그', '약간'은 정상 문장에도 흔하므로 앞/뒤 모두 0.5초 이상 간격이 확인될 때만
    # 확실한 문맥형 머뭇거림으로 사용자 리포트에 포함한다.
    context_confirmed = []
    context_candidates_omitted = []
    timed_index = {id(w): i for i, w in enumerate(timed_words)}
    for w in context_filler_items:
        i = timed_index[id(w)]
        prev_gap = None
        next_gap = None
        if i > 0:
            prev_gap = max(0.0, float(w["start"]) - float(timed_words[i - 1]["end"]))
        if i < len(timed_words) - 1:
            next_gap = max(0.0, float(timed_words[i + 1]["start"]) - float(w["end"]))

        confirmed = (
            prev_gap is not None
            and next_gap is not None
            and prev_gap >= CONTEXT_FILLER_CONFIRM_GAP_SEC
            and next_gap >= CONTEXT_FILLER_CONFIRM_GAP_SEC
        )
        item = {
            "expression": w["word"],
            "start_sec": _round_or_none(w["start"]),
            "gap_before_sec": _round_or_none(prev_gap),
            "gap_after_sec": _round_or_none(next_gap),
        }
        if confirmed:
            item["kind"] = "context_hesitation_confirmed"
            context_confirmed.append(item)
            hesitation_items.append(item)
        else:
            item["kind"] = "context_candidate_omitted"
            context_candidates_omitted.append(item)

    hesitation_items.sort(key=lambda x: (x.get("start_sec") is None, x.get("start_sec") or 0.0))
    hesitation_counts = Counter(item["expression"] for item in hesitation_items)

    # -----------------------------------------------------------------
    # 반복 표현: 같은 단어가 바로 연속된 경우만 보수적으로 기록
    # -----------------------------------------------------------------
    repetition_count = 0
    repetition_items = []
    previous = None
    for w in timed_words:
        token = w["word"]
        if token and token == previous:
            repetition_count += 1
            repetition_items.append({
                "expression": f"{token} {token}",
                "word": token,
                "start_sec": _round_or_none(w["start"]),
            })
        if token:
            previous = token

    # Gross rate: 답변 전체 시간 기준. 시작/끝 정적 구간과 pause를 포함한 체감 속도에 가깝다.
    syllable_count = count_hangul_syllables(text)
    gross_spm = _safe_rate(syllable_count, float(duration) if isinstance(duration, (int, float)) else None)

    # 첫 단어 시작~마지막 단어 종료 span 기준 속도. gross rate와 함께 참고한다.
    timed_duration = None
    if timed_words:
        timed_duration = max(0.0, float(timed_words[-1]["end"]) - float(timed_words[0]["start"]))
    timed_span_spm = _safe_rate(syllable_count, timed_duration)

    # Segment rate와 변동성. 너무 짧거나 내용이 적은 segment는 제외해 과도한 분당 환산을 막는다.
    segment_rates = []
    segment_rate_excluded_count = 0
    for seg in segments_raw:
        seg_text = str(_value(seg, "text", "") or "")
        start = _value(seg, "start")
        end = _value(seg, "end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            segment_rate_excluded_count += 1
            continue
        seg_duration = float(end) - float(start)
        seg_syllables = count_hangul_syllables(seg_text)
        if seg_duration < MIN_SEGMENT_DURATION_SEC or seg_syllables < MIN_SEGMENT_HANGUL_SYLLABLES:
            segment_rate_excluded_count += 1
            continue
        rate = _safe_rate(seg_syllables, seg_duration)
        if rate is not None and math.isfinite(rate):
            segment_rates.append(rate)
        else:
            segment_rate_excluded_count += 1

    segment_rate_mean = mean(segment_rates) if segment_rates else None
    segment_rate_std = pstdev(segment_rates) if len(segment_rates) >= 2 else None
    segment_rate_cv = None
    if segment_rate_mean and segment_rate_mean > 0 and segment_rate_std is not None:
        segment_rate_cv = segment_rate_std / segment_rate_mean

    speech_habits_report = {
        "score_included": False,
        "hesitation": {
            "user_label": "머뭇거림 표현",
            "total_count": len(hesitation_items),
            "counts_by_expression": dict(sorted(hesitation_counts.items())),
            "items": hesitation_items,
            "context_candidates_omitted_count": len(context_candidates_omitted),
            "note": "'그', '약간'은 앞뒤 멈춤이 모두 뚜렷한 경우에만 포함하며 애매한 경우는 리포트에서 제외합니다.",
        },
        "repetition": {
            "user_label": "반복 표현",
            "total_count": repetition_count,
            "items": repetition_items,
        },
    }

    return {
        "text": text,
        "duration_sec": duration,
        "word_count": len([w for w in words if w["word"]]),
        "hangul_syllable_count": syllable_count,
        "gross_syllables_per_min": gross_spm,
        "timed_span_syllables_per_min": timed_span_spm,
        # Compatibility fields retained for existing batch/results.
        "strong_filler_count": len(strong_filler_items),
        "strong_fillers": [w["word"] for w in strong_filler_items],
        "context_filler_count": len(context_filler_items),
        "context_fillers": [w["word"] for w in context_filler_items],
        "context_filler_confirmed_count": len(context_confirmed),
        "repetition_count": repetition_count,
        "repetition_items": repetition_items,
        "hesitation_items": hesitation_items,
        "speech_habits_report": speech_habits_report,
        "pause_gap_0_5_count": len(pause_05),
        "pause_gap_1_0_count": len(pause_10),
        "pause_gap_0_5_total_sec": sum(pause_05),
        "pause_gap_1_0_total_sec": sum(pause_10),
        "max_word_gap_sec": max(gaps) if gaps else None,
        "timed_speech_span_sec": timed_duration,
        "segment_rate_mean": segment_rate_mean,
        "segment_rate_std": segment_rate_std,
        "segment_rate_cv": segment_rate_cv,
        "segment_rates": segment_rates,
        "segment_rate_sample_count": len(segment_rates),
        "segment_rate_excluded_count": segment_rate_excluded_count,
        "segment_rate_min_duration_sec": MIN_SEGMENT_DURATION_SEC,
        "segment_rate_min_hangul_syllables": MIN_SEGMENT_HANGUL_SYLLABLES,
        "word_timestamps_available": bool(timed_words),
        "scoring_note": (
            "raw features only; thresholds/score are not fixed yet. "
            "word-gap pause는 보조값이며 침묵의 주 측정은 음성 신호 기반 분석을 사용한다. "
            "머뭇거림 표현/반복 표현은 사용자 코칭 리포트 전용이며 점수에 넣지 않는다."
        ),
    }
