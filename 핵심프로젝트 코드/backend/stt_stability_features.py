"""STT 상세 결과에서 전달 안정성용 관찰 지표를 계산한다.

이 모듈은 점수를 만들지 않는다. 45개 파일럿 검증용 raw feature만 계산한다.
입력은 stt_service.transcribe_audio_detailed()의 dict와 호환된다.
"""
from __future__ import annotations

import math
import re
from statistics import mean, pstdev
from typing import Any

HANGUL_RE = re.compile(r"[가-힣]")
TRIM_RE = re.compile(r"^[^0-9A-Za-z가-힣]+|[^0-9A-Za-z가-힣]+$")

STRONG_FILLERS = {"어", "음", "저기", "그니까", "뭐랄까"}
CONTEXT_FILLERS = {"그", "약간"}


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

    # exact-token filler counts. '그', '약간'은 문맥상 정상 단어일 수 있어 별도 분리한다.
    strong_filler_items = [w for w in words if w["word"] in STRONG_FILLERS]
    context_filler_items = [w for w in words if w["word"] in CONTEXT_FILLERS]

    # 연속 같은 단어 반복만 보수적으로 센다. 의미상 반복은 언어 AI 단계에서 별도 판단한다.
    repetition_count = 0
    previous = None
    for w in words:
        token = w["word"]
        if token and token == previous:
            repetition_count += 1
        if token:
            previous = token

    # 단어 사이 gap. 음수/역전 timestamp는 무시한다.
    gaps = []
    timed_words = [w for w in words if isinstance(w["start"], (int, float)) and isinstance(w["end"], (int, float))]
    timed_words.sort(key=lambda x: (x["start"], x["end"]))
    for prev, cur in zip(timed_words, timed_words[1:]):
        gap = float(cur["start"]) - float(prev["end"])
        if gap >= 0:
            gaps.append(gap)

    pause_05 = [g for g in gaps if g >= 0.5]
    pause_10 = [g for g in gaps if g >= 1.0]

    # Gross rate: 답변 전체 시간 기준. pause를 포함한 실제 체감 속도에 가깝다.
    syllable_count = count_hangul_syllables(text)
    gross_spm = _safe_rate(syllable_count, float(duration) if isinstance(duration, (int, float)) else None)

    # Segment rate와 변동성. 너무 짧은 segment(<0.5s)는 제외한다.
    segment_rates = []
    for seg in segments_raw:
        seg_text = str(_value(seg, "text", "") or "")
        start = _value(seg, "start")
        end = _value(seg, "end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        seg_duration = float(end) - float(start)
        if seg_duration < 0.5:
            continue
        seg_syllables = count_hangul_syllables(seg_text)
        rate = _safe_rate(seg_syllables, seg_duration)
        if rate is not None and math.isfinite(rate):
            segment_rates.append(rate)

    segment_rate_mean = mean(segment_rates) if segment_rates else None
    segment_rate_std = pstdev(segment_rates) if len(segment_rates) >= 2 else 0.0 if segment_rates else None
    segment_rate_cv = None
    if segment_rate_mean and segment_rate_mean > 0 and segment_rate_std is not None:
        segment_rate_cv = segment_rate_std / segment_rate_mean

    timed_duration = None
    if timed_words:
        timed_duration = max(0.0, float(timed_words[-1]["end"]) - float(timed_words[0]["start"]))

    return {
        "text": text,
        "duration_sec": duration,
        "word_count": len([w for w in words if w["word"]]),
        "hangul_syllable_count": syllable_count,
        "gross_syllables_per_min": gross_spm,
        "strong_filler_count": len(strong_filler_items),
        "strong_fillers": [w["word"] for w in strong_filler_items],
        "context_filler_count": len(context_filler_items),
        "context_fillers": [w["word"] for w in context_filler_items],
        "repetition_count": repetition_count,
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
        "word_timestamps_available": bool(timed_words),
        "scoring_note": "raw features only; thresholds/score are not fixed yet",
    }
