# AI 모의면접 코칭 Agent 백엔드 — Docker 이미지
FROM python:3.11-slim

WORKDIR /app

# 패키지 목록만 먼저 복사해서 설치 (코드만 바뀌었을 때 재설치 방지 → 빌드 속도 향상)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 소스 코드 복사
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
