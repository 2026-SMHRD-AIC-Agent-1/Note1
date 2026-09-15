# A!SK 팀 프로젝트 통합 규격 V1

기준: GitHub `main`

이 문서는 프론트엔드, 백엔드, RAG/언어 AI, 비언어 AI가 **같은 변수명과 같은 데이터 구조**를 사용하기 위한 팀 공통 규격이다.

## 0. 최종 기준 파일

통합 규격의 우선순위는 다음과 같다.

1. `핵심프로젝트 코드/backend/integration_contract_v1.py` — 공통 변수명, 상태값, 이벤트명
2. `핵심프로젝트 코드/backend/integration_models.py` — 캘리브레이션/전달분석 DB 저장 구조
3. 실제 FastAPI 런타임 코드 — `핵심프로젝트 코드/backend/`
4. 이 문서 — 팀 공유용 설명

기존 파일의 오래된 주석이나 실험용 이름이 위 규격과 다르면 **위 1~2번 규격을 따른다.**

RAG 관련 최상위 `rag_ai/integration_contract.json`은 RAG/언어 AI 세부 계약이다. 실제 웹서비스 실행은 `핵심프로젝트 코드/backend/rag_ai/`와 FastAPI 라우터를 기준으로 하며, 둘 사이의 결과 형식은 현재 통일된 상태를 유지한다.

---

## 1. 전체 흐름

```text
사용자 동의
  ↓
기업 / 직무 / 면접유형 선택
  ↓
면접 세션 생성
  ↓
캘리브레이션
  ↓
질문 생성
  ↓
답변 녹화
  ↓
답변 제출
  ↓
STT
  ↓
내용평가 + 전달분석
  ↓
질문별 결과 저장
  ↓
세션 종합
  ↓
최종 리포트
```

면접 유형별 질문 흐름:

- A!SK: `직무이해 → 문제해결 → 협업`
- 심층면접: `첫 질문 → 꼬리질문 1 → 꼬리질문 2 → 꼬리질문 3`

A!SK와 심층면접은 질문 생성 방식만 다르고, 답변 이후 `녹화 → STT → 내용평가 → 전달분석 → 리포트`는 같은 구조를 사용한다.

---

## 2. 연결 ID 규칙

```text
user_id
  ↓
session_id
  ↓
question_id
  ↓
answer_id
  ↓
analysis_id / delivery_analysis_id / events
```

- `user_id`: 사용자
- `session_id`: 면접 한 회차
- `question_id`: 세션의 질문 하나
- `answer_id`: 질문 하나에 대한 답변
- `analysis_id`: 답변의 내용평가
- `delivery_analysis_id`: 답변의 전달분석

새 기능을 만들 때 별도의 연결 ID를 임의로 만들지 않는다.

---

## 3. 면접 세션 규격

프론트 → 백엔드:

```text
user_id
company_id
job_id
interview_type
previous_session_id
```

백엔드 생성:

```text
session_id
```

`interview_type`은 현재 `AISK`, `DEEP_INTERVIEW`를 사용한다.

---

## 4. 질문 규격

RAG → Backend → DB → Frontend에서 동일 이름 사용:

```text
question_id
question_type
question_text
question_reason
evaluation_points
rag_evidence
practice_reason
```

- `evaluation_points`: 항상 3개
- `practice_reason`: 최초 질문은 `null` 가능, 후속/꼬리질문은 사용 가능

심층면접 꼬리질문도 같은 질문 구조로 저장한다.

---

## 5. 답변 규격

Frontend 제출:

```text
session_id
question_id
user_id
audio
video
duration_sec
```

Backend 저장:

```text
answer_id
question_id
user_id
stt_text
video_path
audio_path
duration_sec
```

답변 이후의 내용평가, 전달분석, 타임라인 이벤트는 모두 `answer_id`에 연결한다.

---

## 6. STT 규격

기본 STT:

```text
stt_text
```

상세 STT 프론트 응답:

```text
stt_stability
  ├─ status
  ├─ word_timestamps_available
  ├─ speech_habits
  ├─ pace
  ├─ pause_word_gap_reference
  └─ scoring_note
```

사용자 표현:

- `SPEECH_HESITATION` → 머뭇거림 표현
- `SPEECH_REPETITION` → 반복 표현

둘 다 리포트/코칭용이며 전달점수에 포함하지 않는다.

---

## 7. 내용평가 규격

RAG 입력 핵심:

```text
question_text
evaluation_points
stt_text
```

DB 저장 결과:

```text
analysis_id
scoring_version
job_evaluation
answer_evaluation
job_score
answer_score
strengths
improvements
```

RAG 내부 계산값인 `answer_raw_score`, `answer_base_score`, `answer_excellence_bonus` 등은 현재 내부 검증용이며 DB 필수 저장값이 아니다.

---

## 8. 최종 내용 코칭 규격

```text
content_summary
delivery_summary
priority_focus
next_practice_goal
overall_score
```

중요:

- `overall_score` = **내용 종합 점수**
- 전달 안정성 점수와 합산하지 않는다.

---

# 신규 통합 규격 — 캘리브레이션 / 전달분석

## 9. 캘리브레이션 저장 테이블

DB 테이블:

```text
CALIBRATION_PROFILES
```

세션 1개당 프로파일 1개만 저장한다.

```text
calibration_id
session_id
calibration_version
calibration_status
visual_status
audio_status
visual_baseline
audio_baseline
audio_quality
failure_reasons
technical_error
created_at
updated_at
```

### calibration_status

```text
pending
passed
failed
technical_error
```

### visual_status / audio_status

```text
not_run
passed
failed
technical_error
```

면접은 `calibration_status == "passed"`일 때만 시작할 수 있도록 구현한다.

---

## 10. 시각 baseline

`visual_baseline`은 현재 실제 `nonverbal_ai.CalibrationProfile`의 필드명을 그대로 사용한다.

```text
yaw_baseline
pitch_baseline
roll_baseline
gaze_baseline
ear_baseline
smile_baseline
landmark_motion_baseline
shoulder_width_baseline
shoulder_angle_baseline
detection_rate
```

새로 `head_yaw`, `gaze_x` 같은 별도 이름을 만들지 않는다.

이 값은 좋은 자세의 절대 기준이 아니라 **사용자 개인의 세션 시작 기준값**이다.

---

## 11. 음성 baseline

`audio_baseline`은 기존 `CalibrationProfile` 이름을 유지한다.

```text
voice_mean_db_baseline
voice_f0_mean_baseline
voice_f0_std_baseline
speaking_speed_baseline
```

V1 정책:

- 실제 웹 캘리브레이션에서는 `voice_mean_db_baseline`을 기준값으로 사용
- 피치와 읽기속도는 캘리브레이션 점수에 사용하지 않음
- 기존 호환을 위해 나머지 필드는 저장 가능하지만 `null`이어도 정상

오디오 환경 문제는 `audio_quality`와 `failure_reasons`에 별도로 기록한다.

현재 비언어 AI의 오디오 문제 코드:

```text
MIC_SILENT
TOO_NOISY
LOW_SNR
```

---

## 12. 캘리브레이션 실패 코드

공통 코드:

```text
FACE_NOT_FULLY_VISIBLE
EYES_NOT_BOTH_VISIBLE
SHOULDERS_NOT_BOTH_VISIBLE
VISUAL_DETECTION_LOW
VISUAL_NOT_STABLE
MIC_SILENT
TOO_NOISY
LOW_SNR
CAMERA_PERMISSION_DENIED
MIC_PERMISSION_DENIED
CAMERA_ERROR
FRAME_READ_ERROR
AUDIO_CAPTURE_ERROR
VISUAL_CALIBRATION_FAILED
AUDIO_CALIBRATION_FAILED
```

Backend/AI는 코드 값을 넘기고, Frontend가 코드에 맞는 사용자 안내문을 표시한다.

---

## 13. CalibrationProfile 이동 규칙

```text
Frontend 카메라/마이크
   ↓
비언어 AI 캘리브레이션
   ↓
공통 calibration contract로 변환
   ↓
CALIBRATION_PROFILES 저장
   ↓
session_id로 다시 조회
   ↓
해당 세션 모든 답변 분석에 동일 프로파일 사용
```

A!SK 질문 3개와 심층면접 첫 질문+꼬리질문 전체에서 같은 프로파일을 재사용한다.

중간 재캘리브레이션은 하지 않는다.

---

## 14. 답변별 전달분석 저장 테이블

DB 테이블:

```text
DELIVERY_ANALYSES
```

답변 1개당 1개:

```text
delivery_analysis_id
answer_id
profile_version
status
delivery_profile
delivery_score
created_at
updated_at
```

점수 정책 확정 전:

```text
delivery_score = null
```

측정 실패도 0점으로 저장하지 않는다.

---

## 15. delivery_profile canonical 구조

현재 실제 비언어 AI 출력 구조를 그대로 기준으로 한다.

```text
delivery_profile
  ├─ version
  ├─ delivery_score
  ├─ delivery_score_status
  ├─ measurement
  ├─ components
  │   ├─ speaking_flow
  │   ├─ pace_stability
  │   ├─ volume_stability
  │   ├─ gaze_stability
  │   └─ posture_stability
  ├─ report_only
  ├─ aggregation_policy
  └─ pending_product_decisions
```

기존 `final_score`, `final_score_status`, `head_posture_stability`는 기존 소비자 호환용 alias로만 유지한다.

신규 개발에서는 canonical 이름을 사용한다.

---

## 16. measurement 규격

현재 실제 키를 유지한다.

```text
measurement
  ├─ audio_status
  ├─ audio_issue_codes
  ├─ language_analysis_allowed
  ├─ retake_recommended
  ├─ calibration_used
  └─ calibration_required_for_visual_score
```

component의 `measurement_status` 값:

```text
available
measurement_unavailable
```

`measurement_unavailable`은 0점이 아니다.

---

## 17. gaze_stability

canonical 위치:

```text
delivery_profile.components.gaze_stability
```

현재 핵심 값:

```text
measurement_status
score_eligible
gaze_status
gaze_valid_frame_ratio
center_ratio
deviation_per_min
deviation_time_ratio
meaningful_deviation_min_sec
reference
```

정책:

- 캘리브레이션 성공 후만 `score_eligible=true`
- 의미 있는 시선 이탈: 1초 이상
- 이탈 빈도 + 이탈시간 비율을 함께 사용

---

## 18. posture_stability

canonical 위치:

```text
delivery_profile.components.posture_stability
```

현재 핵심 값:

```text
measurement_status
score_eligible
status
signals
face_deviation_per_min
face_deviation_time_ratio
body_movement_per_min
body_movement_time_ratio
meaningful_deviation_min_sec
reference
```

정책:

- 캘리브레이션 성공 후만 점수 후보
- 의미 있는 자세 이탈: 2초 이상
- 머리 방향 + 어깨 + 상체 위치를 함께 본다.

---

## 19. speaking_flow

canonical 위치:

```text
delivery_profile.components.speaking_flow
```

현재 키:

```text
measurement_status
score_eligible
pause_ratio
pause_per_min
avg_pause_sec
max_pause_sec
long_pause_per_min
scoring_rule
```

침묵은 단순 횟수만으로 자동 감점하지 않는다.

---

## 20. pace_stability

canonical 위치:

```text
delivery_profile.components.pace_stability
```

현재 키:

```text
measurement_status
score_eligible
articulation_rate_units_per_min
timed_span_hangul_syllables_per_min
gross_hangul_syllables_per_min
segment_rate_cv
segment_rate_sample_count
primary_rate_metric
primary_rate_metric_status
```

최종 대표 속도 지표는 점수정책 단계에서 결정한다. 변수 구조는 변경하지 않는다.

---

## 21. volume_stability

canonical 위치:

```text
delivery_profile.components.volume_stability
```

현재 키:

```text
measurement_status
score_eligible
volume_variation_db
average_volume_db_reference
scoring_rule
```

평균 음량의 크기 자체보다 답변 내 음량 변화 안정성을 우선 사용한다.

---

## 22. report_only

점수와 분리된 참고 데이터:

```text
report_only
  ├─ speech_habits
  ├─ blink_per_min
  ├─ smile_episode_count
  ├─ expression_change_count
  ├─ nod_count
  └─ gesture_per_min
```

`머뭇거림 표현`, `반복 표현`은 여기에 포함되며 점수에 넣지 않는다.

---

## 23. 타임라인 이벤트명

공통 저장 구조:

```text
event_id
answer_id
event_type
start_time_sec
end_time_sec
value
```

현재 허용하는 이벤트명:

```text
SPEECH_HESITATION
SPEECH_REPETITION
GAZE_AWAY
FACE_TURNED
LONG_BLINK
SMILE
EXPRESSION_CHANGE
NOD
SHAKE
BODY_MOVEMENT
HAND_GESTURE
LONG_PAUSE
```

`FILLER_WORD`는 기존 비언어 원본의 레거시 이벤트이며 사용자 타임라인에는 저장하지 않는다.

캘리브레이션 전에는 시선/자세 이벤트를 사용자 평가에 사용하지 않고 `LONG_PAUSE` 같은 오디오 이벤트만 안전하게 사용할 수 있다.

---

## 24. 세션 전달 요약

DB 테이블:

```text
DELIVERY_SESSION_SUMMARIES
```

```text
delivery_summary_id
session_id
summary_version
status
question_count
eligible_question_count
component_averages
delivery_score_average
created_at
updated_at
```

`component_averages` 표준 키:

```text
gaze_score
posture_score
speaking_flow_score
pace_score
volume_score
```

점수 정책 확정 전에는 값이 없을 수 있다.

---

## 25. 내용점수와 전달점수

내용:

```text
overall_score
```

사용자 의미: **내용 종합 점수**

전달:

```text
답변별: delivery_score
세션 평균: delivery_score_average
```

현재는 둘을 합산한 단일 총점을 만들지 않는다.

```text
overall_score + delivery_score_average → 합산하지 않음
```

---

## 26. 파트별 소유권

| 데이터 | Frontend | Backend | RAG/언어 AI | 비언어 AI |
|---|---|---|---|---|
| `session_id` | 사용 | 생성/저장 | 참조 | 참조 |
| `question_id` | 사용 | 생성/저장 | 질문 생성 | - |
| `answer_id` | 사용 | 생성/저장 | 참조 | 참조 |
| `stt_text` | 표시 | 저장/전달 | 사용 | 사용 |
| `evaluation_points` | 표시 가능 | 저장 | 생성/사용 | - |
| `calibration_status` | 표시/게이트 | 저장 | - | 판정 결과 제공 |
| `visual_baseline` | - | 저장/전달 | - | 생성/사용 |
| `audio_baseline` | - | 저장/전달 | - | 생성/사용 |
| `delivery_profile` | 표시 | 저장/전달 | - | 생성 |
| `delivery_score` | 표시 | 저장 | - | 점수정책 구현 후 계산 |
| `delivery_score_average` | 표시 | 저장/집계 | - | 점수정책 구현 후 사용 |
| `overall_score` | 표시 | 저장 | 생성 | - |

---

## 27. 팀 개발 규칙

앞으로 팀원이 새 필드를 추가해야 할 경우:

1. 자기 파트에서 임의 이름을 먼저 만들지 않는다.
2. `integration_contract_v1.py`와 이 문서에서 기존 이름으로 표현 가능한지 먼저 확인한다.
3. 정말 새 필드가 필요하면 **통합 규격을 먼저 수정한 뒤** 각 파트 코드에 적용한다.
4. 기존 소비자가 있는 필드를 바꿔야 하면 바로 삭제하지 않고 하위 호환 alias를 둔다.
5. 상태값과 이벤트명은 문자열을 자유 입력하지 않고 통합 규격 상수를 기준으로 한다.

이 규칙을 지키면 2단계부터 프론트/백엔드/RAG/비언어 AI가 병렬로 개발해도 나중에 변수명과 구조를 다시 맞추는 작업을 최소화할 수 있다.
