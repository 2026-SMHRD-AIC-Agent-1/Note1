from stt_stability_features import analyze_stt_stability


def test_stt_stability_features_basic():
    detail = {
        "text": "어 저는 데이터 분석을 했고 그리고 그리고 결과를 개선했습니다. 이상입니다.",
        "duration_sec": 6.0,
        "words": [
            {"word": "어", "start": 0.0, "end": 0.2},
            {"word": "저는", "start": 0.3, "end": 0.6},
            {"word": "데이터", "start": 0.7, "end": 1.1},
            {"word": "분석을", "start": 1.2, "end": 1.6},
            {"word": "했고", "start": 2.8, "end": 3.1},
            {"word": "그리고", "start": 3.2, "end": 3.6},
            {"word": "그리고", "start": 3.7, "end": 4.1},
            {"word": "결과를", "start": 4.2, "end": 4.6},
            {"word": "개선했습니다.", "start": 4.7, "end": 5.4},
            {"word": "이상입니다.", "start": 5.5, "end": 5.9},
        ],
        "segments": [
            {"text": "어 저는 데이터 분석을 했고", "start": 0.0, "end": 3.1},
            {"text": "그리고 그리고 결과를 개선했습니다.", "start": 3.2, "end": 5.4},
            {"text": "이상입니다.", "start": 5.5, "end": 5.9},
        ],
    }

    result = analyze_stt_stability(detail)

    # '그리고' 속 '그'를 필러로 잘못 세지 않아야 한다.
    assert result["strong_filler_count"] == 1
    assert result["context_filler_count"] == 0
    # 연속된 '그리고 그리고'는 보수적 반복 1회로 잡는다.
    assert result["repetition_count"] == 1
    # 1.6 -> 2.8 사이 1.2초 공백.
    assert result["pause_gap_1_0_count"] == 1
    # 문장부호/영문/숫자가 아니라 한글 음절만 속도 계산에 사용한다.
    assert result["hangul_syllable_count"] > 0
    assert result["word_timestamps_available"] is True
    # 짧은 '이상입니다' segment는 속도 변동 계산에서 제외되어야 한다.
    assert result["segment_rate_sample_count"] == 2
    assert result["segment_rate_excluded_count"] == 1
    # timestamp span 기준 속도도 계산돼야 한다.
    assert result["timed_span_syllables_per_min"] is not None

    return result


if __name__ == "__main__":
    result = test_stt_stability_features_basic()
    print("[PASS] STT stability feature test")
    print(result)
