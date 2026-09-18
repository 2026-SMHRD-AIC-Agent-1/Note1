# AI 모의면접 - 재명 RAG / 언어 AI 파트

## 1. 목적
대기업·공기업 1차 서류 합격 후 실제 면접을 준비하는 지원자를 대상으로, 기업·직무·면접유형별 공개자료를 RAG로 검색해 질문과 평가포인트를 생성하고 답변 내용 분석·종합 코칭·반복연습 비교까지 제공한다.

현재 PoC
- 기업: SK하이닉스
- 직무: System Architecture / Software Solution
- 면접유형: A!SK 영상 인터뷰 / 심층 인터뷰
- 질문유형: 직무이해 / 문제해결 / 협업

## 2. 핵심 루프
면접 → 답변마다 내부 평가 1회 및 저장 → 약점에 맞는 꼬리질문 → 면접 종료 → 저장된 평가로 종합평가 + 답변별 평가 + 점수 흐름 → 다음 연습목표

## 3. 재명 파트 기능
1. RAG 자료 Loading / Chunking / Embedding / FAISS 검색
2. A!SK 질문 3개 생성
3. 심층면접 첫 질문 1개 생성
4. 심층면접 답변을 바탕으로 꼬리질문을 최대 3개까지 순차 생성
5. 각 질문마다 평가포인트 3개 생성
6. STT 답변 내용 분석
7. 직무 핵심 반영도 / 답변 구성 충실도 계산
8. 심층면접 각 답변을 1회 분석하고 결과 저장
9. 심층면접 종료 후 저장된 평가만 사용해 종합평가 생성
10. 답변별 점수·강점·보완점 제공
11. 첫 답변부터 마지막 답변까지 점수 흐름 제공
12. 동일 입력 반복분석으로 점수 안정성 확인
13. MCP를 통한 외부 공식자료 보강(후속 적용)

## 4. 심층면접 실제 사용자 흐름
사용자가 면접 도중 매 답변마다 점수를 보는 구조가 아니다.

첫 질문 → 답변 → 꼬리질문 1 → 답변 → 꼬리질문 2 → 답변 → 꼬리질문 3 → 답변 → 최종 결과

시스템 내부 흐름은 다음과 같다.

첫 질문 → 답변 → `analyze_deep_turn()` 1회 분석·저장 → 꼬리질문 1 → 답변 → 1회 분석·저장 → 꼬리질문 2 → 답변 → 1회 분석·저장 → 꼬리질문 3 → 답변 → 1회 분석·저장 → `analyze_deep_session()` 종합

- 꼬리질문은 최대 3개까지만 생성한다.
- 다음 꼬리질문 생성 시 직전 답변의 부족한 부분을 내부적으로 확인한다.
- 이미 확인한 내용을 반복하지 않도록 `previous_followups`를 전달할 수 있다.
- 각 꼬리질문에는 `evaluation_points` 3개가 포함된다.
- 면접 중 답변별 점수는 사용자에게 노출하지 않아도 된다.
- 각 답변 평가는 한 번만 수행하고 Backend/DB에 저장하는 것을 기본으로 한다.
- 면접 종료 후 `analyze_deep_session()`은 답변을 다시 채점하지 않고 저장된 `analysis`를 그대로 사용한다.

## 5. 심층면접 최종 결과 구조
`analyze_deep_session(turns)`는 다음 3단 구조를 반환한다.

1. 종합평가
- 전체 직무점수: 저장된 답변별 직무점수 평균
- 전체 답변 구성점수: 저장된 답변별 답변 구성점수 평균
- 종합 강점
- 우선 보완점
- 다음 연습목표

2. 답변별 상세평가
- 몇 번째 답변인지
- 질문 내용
- 당시 저장된 직무점수
- 당시 저장된 답변 구성점수
- 강점
- 보완점
- 세부 평가결과

3. 답변별 점수 흐름
- 직무점수 배열
- 답변 구성점수 배열
- 첫 답변과 마지막 답변의 점수 차이
- 점수 방향: `상승 / 하락 / 동일`
- 가장 낮은 점수를 받은 답변과 가장 높은 점수를 받은 답변

중요: 꼬리질문마다 난이도와 평가포인트가 다르므로 점수 흐름만으로 지원자의 실력이 향상·하락했다고 단정하지 않는다. 종합 코칭에서는 실제 저장된 강점·보완점에 근거해 어떤 내용이 부족했고 이후 답변에서 무엇이 구체화됐는지를 설명한다.

예시 호출:

```python
turn1 = ai.analyze_deep_turn(deep_question, deep_answer)
turn2 = ai.analyze_deep_turn(followup1, followup1_answer)
turn3 = ai.analyze_deep_turn(followup2, followup2_answer)
turn4 = ai.analyze_deep_turn(followup3, followup3_answer)

# 실제 서비스에서는 각 turn의 analysis를 Backend/DB에 즉시 저장한다.
turns = [turn1, turn2, turn3, turn4]
result = ai.analyze_deep_session(turns)
```

이미 별도로 `analyze_answer()`를 실행해 저장한 결과가 있다면 다음과 같이 전달할 수도 있다.

```python
turns = [
    {"question_data": deep_question, "stt_text": deep_answer, "analysis": deep_result},
    {"question_data": followup1, "stt_text": followup1_answer, "analysis": followup1_result},
    {"question_data": followup2, "stt_text": followup2_answer, "analysis": followup2_result},
    {"question_data": followup3, "stt_text": followup3_answer, "analysis": followup3_result},
]

result = ai.analyze_deep_session(turns)
```

## 6. 역할 경계
- Frontend: 기업/직무/면접유형 선택, 질문 표시, 답변 녹화, 최종 결과 표시
- Backend: Session/Question/Answer ID, 파일 저장, STT 실행, 답변별 analysis 저장, DB 저장, 각 AI 호출
- RAG/언어 AI: 질문·평가포인트·답변분석·종합코칭·꼬리질문
- 비언어 AI: 관찰 가능한 영상/음성 측정값과 전달 안정성 결과

## 7. GitHub 병합 원칙
- 각 파트 구현은 독립 폴더/브랜치에서 작업한다.
- 내부 구현보다 입출력 JSON 규격을 먼저 고정한다.
- API 공통키: company, job, interview_type, question_type, evaluation_points, stt_text
- OpenAI API Key 등 비밀값은 코드에 저장하지 않고 환경변수로 관리한다.
- RAG 원문자료는 GitHub에 중복 저장하지 않고 별도 자료 폴더를 `RAG_BASE_PATH` 또는 `base_path`로 연결한다.
- main/develop 병합 전 샘플 Payload로 연동 테스트한다.

## 8. 점수 해석 주의
- 기업 내부 평가표나 합격 가능성을 추정하지 않는다.
- 점수는 연습용 지표다.
- 현재 점수체계는 `v8_answer_base95_excellence5`이다.
- 직무평가는 평가포인트 3개마다 공통 세부조건 5개를 True/False로 판단하고 Python이 100점으로 환산한다.
- 같은 답변이 여러 평가포인트의 핵심 요구에 실제로 직접 답하면 각각 인정할 수 있다.
- 세부조건은 독립적으로 판단한다. 검증이 없다는 이유로 다른 세부조건까지 연쇄적으로 낮추지 않는다.
- 기술 질문의 5번째 세부조건은 재측정·재실험·전후 비교·기준선 비교 등 실제 검증 과정이 있어야 인정한다.
- 답변 구성 기본평가는 최대 95점이고, 모든 답변에 별도 우수답변 조건 4개를 적용해 최대 +5점의 보너스를 더한다.
- 심층면접 종합점수는 저장된 답변별 점수의 평균을 사용한다.
- 질문마다 난이도와 평가포인트가 다르므로 첫 답변과 마지막 답변의 점수 차이는 `점수 흐름`으로만 표시하고, 그것만으로 실력 향상·하락을 단정하지 않는다.

## 9. MCP 적용 방향
MCP는 RAG를 대체하지 않고 외부 검색 도구를 연결해 기업·직무·면접유형별 공식 공개자료를 찾아 검증 후 RAG에 보강하는 용도로 적용한다.