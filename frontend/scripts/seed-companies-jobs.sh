#!/usr/bin/env bash
# 회사/직무 마스터 데이터를 1회 등록하는 스크립트입니다.
#
# 프론트엔드에는 "기업/직무 추가" 기능이 없습니다 (실제 서비스에서는
# 사용자가 아니라 관리자/백엔드가 이 데이터를 미리 넣어두는 것이 맞기
# 때문입니다). 대신 이 스크립트로 백엔드 API에 직접 등록합니다.
#
# 값은 backend/.env.example의 RAG_DEFAULT_COMPANY / RAG_DEFAULT_JOB와
# rag_data/02_JOB리포트_SystemArchitecture_SoftwareSolution.txt 파일명을
# 그대로 따랐습니다 (임의로 지어내지 않았습니다).
#
# 사용법:
#   chmod +x scripts/seed-companies-jobs.sh
#   API_BASE=http://127.0.0.1:8000 ./scripts/seed-companies-jobs.sh

set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"

echo "1) 기업 등록: SK하이닉스"
COMPANY_JSON=$(curl -s -X POST "$API_BASE/companies" \
  -H "Content-Type: application/json" \
  -d '{"company_name": "SK하이닉스", "description": "backend .env.example RAG_DEFAULT_COMPANY"}')
echo "$COMPANY_JSON"
COMPANY_ID=$(echo "$COMPANY_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['company_id'])")

echo "2) 직무 등록: System Architecture / Software Solution (company_id=$COMPANY_ID)"
curl -s -X POST "$API_BASE/jobs" \
  -H "Content-Type: application/json" \
  -d "{\"company_id\": $COMPANY_ID, \"job_name\": \"System Architecture / Software Solution\", \"job_category\": \"개발\"}"

echo
echo "완료. 프론트엔드 설정 화면의 '지원 기업/직무' 드롭다운에서 바로 선택할 수 있습니다."
