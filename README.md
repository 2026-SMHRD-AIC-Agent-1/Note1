# AI 모의면접 코칭 Agent — DB + RAG·언어 AI 연동 백엔드

## 구성
```
ai-interview-backend/
├── main.py                        # 진입점 — 라우터 연결 + AI/STT 서비스 초기화
├── database.py                    # DB 연결 (.env에서 설정 읽음)
├── models.py                       # 확정 13개 테이블 (SQLModel)
├── models_proposed.py              # [변경 제안] 아직 팀 합의 전인 테이블만 (현재 1개)
├── interview_ai_service_v0_1.py    # 재명씨(RAG·언어 AI) 서비스 원본 (수정 없이 그대로)
├── ai_service_client.py            # 위 서비스를 안전하게 초기화/재사용하는 래퍼
├── stt_service.py                  # 답변 음성 파일 → 텍스트 변환(STT) 래퍼
├── routers/                         # 테이블·기능별 API (아래 "API 목록" 참고)
├── test_smoke.py                    # DB 틀 자체 동작 확인 (10개 확정 테이블)
├── test_ai_payload_ingest.py        # 재명씨 실제 샘플로 DB 스키마 검증
├── ai_interview_sample_payload_v0_1.json   # 위 테스트가 사용하는 실제 샘플 데이터
├── rag_data/                         # RAG 검색용 원본 자료
├── .env.example / Dockerfile / docker-compose.yml / requirements.txt
└── README.md
```

## 실행 방법

### 1) 먼저 DB 틀만 확인 (AI 없이)
```bash
pip install -r requirements.txt
python test_smoke.py
```

### 2) 재명씨 실제 샘플로 스키마 검증
```bash
python test_ai_payload_ingest.py
```
`evaluation_points`, `rag_evidence`, 비언어 14개 값까지 원본 JSON과 100% 동일하게 저장·복원되는지 확인합니다.

### 3) 서버 실행
```bash
cp .env.example .env
# .env에 OPENAI_API_KEY, RAG_DATA_DIR을 채우면 /ai/*, 업로드 STT까지 전부 동작
uvicorn main:app --reload
```
`http://127.0.0.1:8000/docs`에서 전체 API 확인/테스트 가능. `GET /health`로 AI·STT 서비스 준비 상태 확인 가능.

## 환경 변수 (.env)
| 변수 | 설명 | 기본값 |
|---|---|---|
| `DATABASE_URL` | DB 연결 주소 | `sqlite:///./app.db` |
| `CORS_ORIGINS` | Frontend 허용 주소 | `http://localhost:3000` |
| `OPENAI_API_KEY` | RAG·언어 AI 및 STT용 API 키 | (비어있음) |
| `OPENAI_MODEL` | 질문·분석·코칭 생성에 쓸 모델 | `gpt-5.4-mini` |
| `RAG_DATA_DIR` | RAG 원문 자료 폴더 (이 서버 기준 실제 경로) | `./rag_data` |
| `RAG_DEFAULT_COMPANY` / `RAG_DEFAULT_JOB` | 기본 기업/직무 | SK하이닉스 / System Architecture |
| `UPLOAD_DIR` | 답변 녹화 파일(음성/영상) 저장 폴더 | `./uploads` |

`OPENAI_API_KEY`가 없어도 서버는 정상적으로 뜹니다. `/ai/*`와 답변 업로드(STT)만
비활성화되고 나머지 API는 그대로 동작합니다.

## RAG 원본 자료
`rag_data/`에 재명씨가 전달한 원본 7개(텍스트)가 들어있습니다. 공식 채용 PDF는
전체가 이미지 기반이라 텍스트 추출이 안 되어서, 팀 결정에 따라 핵심 내용을 정리한
`08_2026하반기_JD_직무구분_핵심추출.txt`를 대신 검색 자료로 씁니다 (원본 PDF는
출처 확인용으로만 보관, 검색에는 자동으로 제외됨).

## 회차(반복 연습) 추적
`InterviewSessions`에 `attempt_no`(몇 회차인지)와 `previous_session_id`(이전 세션 참조)가
있습니다. 세션 생성 시 `previous_session_id`만 넘기면 `attempt_no`는 "이전 회차+1"로
자동 계산되므로 Frontend/AI가 직접 계산할 필요가 없습니다. 두 세션 간 실제 지표 비교는
`SESSION_COMPARISONS`가 담당합니다.

## API 목록

### 핵심 테이블 CRUD
| 테이블 | 엔드포인트 |
|---|---|
| USERS | `POST /users`, `GET /users`, `GET /users/{id}` |
| COMPANIES | `POST /companies`, `GET /companies` |
| JOBS | `POST /jobs`, `GET /jobs`, `GET /companies/{id}/jobs` |
| RAG_DOCUMENTS | `POST /rag-documents`, `GET /rag-documents` |
| INTERVIEW_SESSIONS | `POST /interview-sessions`, `GET /interview-sessions`, `GET /interview-sessions/{id}`, `GET /interview-sessions/{id}/coaching`, `GET /interview-sessions/users/{user_id}/history` |
| INTERVIEW_QUESTIONS | `POST /interview-questions`, `GET /interview-questions`, `GET /interview-sessions/{id}/questions` |
| USER_ANSWERS | `POST /user-answers`, `GET /user-answers`, `GET /user-answers/{id}` |
| NONVERBAL_METRICS | `POST /nonverbal-metrics`, `GET /nonverbal-metrics` |
| NONVERBAL_EVENTS | `POST /nonverbal-events`, `GET /nonverbal-events`, `GET /user-answers/{id}/events` |
| ANSWER_ANALYSES | `POST /answer-analyses`, `GET /answer-analyses` |
| FINAL_COACHINGS | `POST /final-coachings`, `GET /final-coachings` |
| SESSION_TECHNICAL_EVENTS | `POST /session-technical-events`, `GET /session-technical-events`, `GET /session-technical-events/sessions/{id}` |
| SESSION_COMPARISONS | `POST /session-comparisons`, `GET /session-comparisons` |

### RAG·언어 AI 연동 (`/ai/*`)
| 엔드포인트 | 역할 |
|---|---|
| `POST /ai/sessions/{id}/generate-questions` | 세션의 기업·직무·면접유형으로 질문 3개 생성 후 저장 |
| `POST /ai/user-answers/{id}/analyze` | 저장된 STT 답변을 분석해 `ANSWER_ANALYSES`에 저장 |
| `POST /ai/sessions/{id}/generate-coaching` | 세션의 질문 3개+분석+비언어값을 종합해 `FINAL_COACHINGS` 생성 |
| `POST /ai/sessions/{next_id}/generate-followup-question?previous_session_id={id}` | 이전 세션 코칭(약점)을 반영한 후속 질문 생성 (1회차→2회차 연결) |

### 답변 녹화 업로드 (`/user-answers/submit`)
| 엔드포인트 | 역할 |
|---|---|
| `POST /user-answers/submit` | 음성(필수)/영상(선택) 파일 업로드 → 저장 → STT 변환 → `USER_ANSWERS` 저장 → (AI 준비 시) 분석까지 한 번에 수행 |
| `GET /user-answers/{id}/video` | 저장된 답변 영상 파일을 직접 스트리밍 (Frontend 재생용) |
| `GET /user-answers/{id}/audio` | 저장된 답변 음성 파일을 직접 스트리밍 |

Frontend는 녹화 시작/종료 + `MediaRecorder`로 만든 Blob을 `FormData`로 이 엔드포인트에
보내기만 하면 됩니다. STT나 분석 로직을 Frontend가 알 필요는 없습니다. 업로드 검증은
확장자와 브라우저가 보내는 `Content-Type`을 함께 확인하며, 재생 API는 저장 경로가
`UPLOAD_DIR` 밖을 가리키지 않는지 검사해 임의 파일 노출을 막습니다.

### 공통
| 엔드포인트 | 역할 |
|---|---|
| `GET /health` | 서버·AI 서비스·STT 서비스 준비 상태 확인 |

## 아직 미확정인 부분
- `models_proposed.py`의 `UserConsentsProposed`(개인정보 동의) 하나만 남아있습니다.
  세션 단위/사용자 단위 중 어느 쪽으로 동의를 받을지 팀 합의 필요.
- `NONVERBAL_EVENTS`, `SESSION_TECHNICAL_EVENTS`는 테이블 구조는 확정됐지만,
  `event_type`에 정확히 어떤 값들을 쓸지는 비언어 AI·Frontend 담당과 계속 협의 중입니다.
- `FinalCoachings.overall_score`는 필드만 준비되어 있고 계산 로직은 없습니다
  (점수 산정 기준을 팀이 정하지 않아, 근거 없는 점수를 만들지 않기 위함).
  기준이 정해지면 이 필드를 채우는 로직만 추가하면 `SESSION_COMPARISONS`의
  점수 비교도 자동으로 채워집니다.
