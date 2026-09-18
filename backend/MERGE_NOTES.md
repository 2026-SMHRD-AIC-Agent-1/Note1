# 최종 병합본 안내

기준: `ai-interview-backend 7번(1).zip`

병합: `Note1-main(3).zip`에서 실질적으로 변경된 RAG 코드(`rag_ai/rag_ai_service.py`)를 선별 반영.

추가: 이전에 확보된 SK하이닉스 RAG 원본 자료 8개를 `rag_data/`에 복원하여 포함.

비언어 분석: 실제 팀원 데이터 연동은 하지 않으며 기존 구조만 유지.

주의:
- 실제 `.env`, API 키, 사용자 DB, 업로드 영상/음성은 포함하지 않습니다.
- `app.db`가 기존에 있다면 새 모델/컬럼 변경에 맞춰 별도 마이그레이션 또는 재생성이 필요할 수 있습니다.
- RAG 원본 자료를 GitHub에 올릴지 여부는 팀 저장소 정책에 따라 최종 결정하세요.

## 2026-09-10 MVP 보완 반영

1. 실제 실행 경로를 `rag_ai/rag_ai_service.py`로 통합했습니다. `interview_ai_service_v0_1.py`는 기존 import 호환용 facade만 남겼습니다.
2. `rag_data/rag_data`로 중복된 원본 폴더를 `rag_data/` 바로 아래로 정리했습니다. 코드에서도 중첩 경로를 발견하면 자동 대응합니다.
3. 통합 RAG 서비스에 PDF 읽기를 추가했습니다. 단, 현재 SK하이닉스 원본 PDF가 이미지 기반이라 텍스트 추출이 안 되면 자동으로 건너뛰며, 08번 텍스트 추출본은 정상 사용됩니다.
4. `Solution SW`와 `System Architecture / Software Solution` 분리를 08번 JD 처리에 실제 실행 경로로 반영했습니다.
5. 답변 분석의 `job_score`, `answer_score`, `scoring_version`을 `ANSWER_ANALYSES`에 저장합니다.
6. 세션 `overall_score`는 답변별 `job_score`와 `answer_score`의 평균을 먼저 구한 뒤, 그 답변별 종합점수 평균으로 계산해 `FINAL_COACHINGS`에 저장합니다.
7. 1회차/2회차 비교는 비언어 데이터가 없어도 `overall_score` 변화량을 보여주도록 보완했습니다. 비언어 데이터가 추가되면 기존 지표 비교도 같이 사용할 수 있습니다.
8. 같은 답변을 다시 분석하거나 녹화 제출을 재시도할 때 `ANSWER_ANALYSES` 중복 생성이 발생하지 않도록 upsert 방식으로 보완했습니다.
9. 사용자 조회 응답에서 `password_hash`가 노출되지 않도록 `UserPublic` 응답 모델을 적용했습니다.
10. 비언어 분석 자체는 이번 보완 범위에서 구현하지 않았습니다. 녹화→업로드→STT는 기존 MVP 구현을 유지했습니다.
