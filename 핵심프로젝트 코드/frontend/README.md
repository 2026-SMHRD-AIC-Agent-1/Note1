# AI 모의면접 코칭 — Frontend (React + Vite)

백엔드 최신버전(`ai-interview-backend_MVP_V2_6FIX_CLEAN_PIPFIX`)의 실제 API
(`main.py`, `routers/*.py`, `ai_pipeline.py`, `uploads.py`, `consents.py`,
`session_comparisons.py`, `session_technical_events.py`)를 그대로 호출하는
React 프론트엔드입니다. 백엔드에 없는 엔드포인트나 아직 연동되지 않은 기능은
만들지 않았고, 대신 화면에 "아직 준비되지 않음" 안내로 표시했습니다 (아래
"알려진 한계" 참고).

**디자인**: 업로드해주신 랜딩페이지 이미지를 기준으로 라이트 테마(흰 배경 + 파란
강조색 `#3159e8`)로 전환했습니다. `LandingPage.jsx`가 첫 화면이고, "지금
시작하기"를 누르면 기존 4단계 흐름(동의 → 설정 → 면접 → 리포트)으로 들어갑니다.
이미지 속 인물 사진은 저작권이 있는 특정 스톡 사진이라 그대로 재현할 수 없어서,
대신 실제 리포트 화면과 같은 지표를 보여주는 자체 제작 미리보기 카드로
대체했습니다.

## ⚠️ 백엔드에 꼭 적용해야 하는 수정 1가지

`database.py`의 `get_session()`이 `Session(engine, expire_on_commit=False)`로
되어 있는지 확인하세요. 그냥 `Session(engine)`이면, `ai_pipeline.py`의 질문
3개 생성 루프에서 중간 `commit()`이 앞서 만든 질문 객체들의 값을 초기화시켜서,
"첫 번째·두 번째 질문이 빈 값으로 온다" 증상이 다시 나타납니다. (이전에 한 번
겪었던 것과 같은 원인입니다 — 이번 zip에는 그 수정이 빠져 있었습니다.)

```python
def get_session():
    with Session(engine, expire_on_commit=False) as session:
        yield session
```

## 실행 방법

### 1) 백엔드 실행
```bash
cd ai-interview-backend_MVP_V2_6FIX_CLEAN_PIPFIX
pip install -r requirements.txt
cp .env.example .env
# .env에 OPENAI_API_KEY 채우기 (질문 생성/답변 분석/STT에 필요)
uvicorn main:app --reload
```
`http://127.0.0.1:8000/health` 에서 `ai_service_ready`·`stt_service_ready`가
모두 `true`인지 확인하세요.

### 2) 기업·직무 마스터 데이터 1회 등록 (프론트에는 추가 기능이 없음)
```bash
chmod +x scripts/seed-companies-jobs.sh
API_BASE=http://127.0.0.1:8000 ./scripts/seed-companies-jobs.sh
```
(백엔드가 앱 시작 시 `rag_data/`를 `RAG_DOCUMENTS`에 자동 동기화하지만,
`COMPANIES`/`JOBS` 마스터 데이터는 별도로 등록해야 합니다.)

### 3) 프론트엔드 실행
```bash
npm install
cp .env.example .env
npm run dev
```
`http://localhost:3000` 접속.

## 실제로 호출하는 API (지어낸 엔드포인트 없음)

| 화면 | 호출 |
|---|---|
| 시작하기 | `POST /users`, `GET /users`(이메일 조회용), `POST /consents` (AUDIO_RECORDING·VIDEO_RECORDING·ANALYSIS·DATA_RETENTION 4건) |
| 맞춤 설정 | `GET /companies`, `GET /companies/{id}/jobs`, `POST /interview-sessions`, `POST /ai/sessions/{id}/generate-questions` |
| 면접 진행 | `POST /user-answers/submit` (오디오 필수·비디오 선택·duration_sec 포함, FormData), 필요 시 `POST /ai/user-answers/{id}/analyze`, `GET /answer-analyses`, `POST /ai/sessions/{id}/generate-coaching` |
| 종합 리포트 | `GET /user-answers/{id}/events`, `GET /user-answers/{id}/video`, `GET /nonverbal-metrics`, `POST /session-comparisons`, `POST /interview-sessions`(previous_session_id 포함) + `POST /ai/sessions/{id}/generate-followup-question` |
| 공통 | `GET /health` |

## 백엔드 최신버전 반영 — 무엇이 왜 바뀌었는지

- **동의(consent) 타입이 바뀌었습니다**: 예전 `VIDEO_AUDIO_COLLECTION` 하나 대신,
  `AUDIO_RECORDING`/`VIDEO_RECORDING`/`ANALYSIS`/`DATA_RETENTION` 4가지를 각각
  등록해야 합니다. `uploads.py`가 답변 업로드 시점에 `AUDIO_RECORDING`(필수),
  `VIDEO_RECORDING`(영상 있으면 필수), `ANALYSIS`(분석하려면 필수)를 실시간으로
  확인해서, 없으면 403으로 막습니다. 화면은 체크박스 하나지만 내부적으로 4건을
  한 번에 등록합니다 (`EntryPage.jsx`의 `grantAllConsents`).
- **`POST /user-answers/submit` 응답이 가벼워졌습니다**: 예전엔 분석 결과 전체를
  바로 돌려줬지만, 이제 `{ answer_id, stt_text, analysis_id, note }`만 옵니다.
  `analysis_id`가 있으면 `GET /answer-analyses`에서 찾아 채우고, 없으면(AI가
  업로드 시점에 준비 안 됐던 경우) `POST /ai/user-answers/{id}/analyze`를 한 번
  더 직접 호출합니다 (`InterviewPage.jsx`).
- **답변 분석에 숫자 점수가 추가됐습니다**: `job_score`/`answer_score`(0~100대
  숫자)와 `scoring_version`이 생겼습니다. 리포트 화면에 평가 라벨과 함께 점수도
  표시합니다.
- **"다음 회차" 흐름이 2단계로 바뀌었습니다** (옛 `/practice/*`는 완전히 삭제됨):
  1. `POST /interview-sessions`에 `previous_session_id`를 넣어 다음 회차 세션을
     먼저 만듭니다 (`attempt_no`는 백엔드가 자동 계산).
  2. `POST /ai/sessions/{새 세션 id}/generate-followup-question?previous_session_id={이전 세션 id}`로
     1회차 코칭(우선 개선점·다음 목표)을 반영한 꼬리질문 1개를 생성합니다.
- **회차 비교가 `SESSION_COMPARISONS` 테이블/엔드포인트로 바뀌었습니다**:
  `POST /session-comparisons`에 `{first_session_id, second_session_id}`를
  보내면 종합점수 변화(`first_overall_score`/`second_overall_score`/
  `score_change`)와 비언어 지표 변화 요약을 계산해줍니다.
- **`/technical-events` → `/session-technical-events`로 이름이 바뀌었습니다**
  (현재 화면에서는 호출하지 않지만, `api.js`의 경로만 맞춰뒀습니다).

## 리포트 구조 (중복 제거)

"2. AI 종합 코칭"에 주요 강점·개선 포인트·가장 먼저 고칠 점을 한데 모아서, 예전에
따로 있던 3~5번 섹션과 내용이 겹치지 않도록 정리했습니다. 이후 섹션 번호는
3(다음 연습 목표)~8(비언어 분석 요약)로 당겨졌습니다. 1번 상단 요약에서
면접일시는 뺐고, 종합/최고/최저 점수는 막대그래프(100점 만점 표시)로 보여줍니다.

## 녹화 파일은 어디에 저장되나요

`routers/uploads.py` 기준으로 백엔드 로컬 디스크에 저장됩니다 (클라우드 아님):
```
backend/uploads/audio/  ← 답변 음성 파일 (webm)
backend/uploads/video/  ← 답변 영상 파일 (webm)
```
파일명은 UUID이고, 실제 경로는 `UserAnswers.audio_path`/`video_path`에 DB로
저장됩니다. 프론트는 이 경로를 직접 열지 않고 `GET /user-answers/{id}/video`·
`/audio`로만 스트리밍해서 재생합니다. 저장 위치는 `UPLOAD_DIR` 환경변수로
바꿀 수 있습니다.

## 자주 겪는 문제

**"AI 서비스가 아직 준비되지 않았습니다" (503)** — `GET /health`의
`ai_service_ready`/`stt_service_ready`가 `false`인지 먼저 확인하고, 백엔드
`.env`의 `OPENAI_API_KEY`를 채운 뒤 `uvicorn`을 재시작하세요.

**질문 3개 중 일부가 빈 값으로 옴** — 위 "백엔드에 꼭 적용해야 하는 수정" 항목을
확인하세요 (`expire_on_commit=False`).

**답변 제출이 403으로 막힘** — 동의(consent)가 없는 경우입니다. `EntryPage`에서
동의 화면을 다시 통과했는지 확인하세요. 에러 메시지에 어떤 `consent_type`이
빠졌는지 그대로 나옵니다.

## 알려진 한계 (일부러 만들지 않은 것)

- **비언어 분석(NONVERBAL_METRICS)이 비어 있을 수 있음**: 이 백엔드에는 실시간
  웹캠 비언어 분석(MediaPipe 등)을 자동으로 저장하는 파이프라인이 아직
  연동되어 있지 않습니다. 프론트는 `GET /nonverbal-metrics`를 조회해 값이
  있으면 보여주고, 없으면 "아직 없음" 안내만 표시합니다.
- **얼굴 미검출/2인 이상 감지(FR-AI-010의 일부)는 구현하지 않음**: 실시간 얼굴
  인식 모델이 필요한데 해당 로직이 없어서 지어내지 않았습니다. 대신 표준
  `getUserMedia` 권한 거부만 감지해 세션 진행을 막습니다.
- **로그인/인증 없음**: `USERS.password_hash`는 채우지만 실제 비밀번호 검증이나
  세션 토큰은 없습니다. 이메일로 기존 계정을 찾거나 새로 만드는 MVP용 흐름입니다.
- **재방문 사용자는 이메일로 인식됩니다**: 전용 조회 엔드포인트가 없어서
  `GET /users` 전체 목록에서 이메일이 일치하는 계정을 찾습니다.
- **질문 음성 읽기(TTS)/다시듣기는 브라우저 내장 기능**: 백엔드에 TTS가 없어서
  브라우저의 `SpeechSynthesis` API로 클라이언트에서만 처리합니다.
- **다음 회차는 질문 1개**: `generate-followup-question`이 실제로 1개만
  생성하도록 구현되어 있습니다.
- **기업/직무는 선택만 가능, 추가는 관리자 몫**: `scripts/seed-companies-jobs.sh`로
  최초 1회 등록하세요.
