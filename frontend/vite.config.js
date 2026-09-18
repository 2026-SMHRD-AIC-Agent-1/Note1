import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 백엔드 main.py의 기본 CORS_ORIGINS 값(http://localhost:3000)과 맞추기 위해
// 개발 서버 포트를 3000으로 고정합니다. 백엔드 .env의 CORS_ORIGINS를 바꾸면
// 이 값도 함께 바꿔주세요.
//
// [2026-09 시연용] ngrok 무료 계정은 고정 공개 주소를 1개만 주기 때문에,
// 백엔드(8000)를 따로 터널링하는 대신 Vite 개발 서버가 아래 경로들을
// 그대로 백엔드(http://127.0.0.1:8000)로 중계(proxy)하게 했습니다. 그러면
// ngrok 터널은 프론트(3000)용 1개만 열면 되고, 프론트의 fetch 호출도
// VITE_API_BASE를 비워두면(같은 오리진 상대경로) 자동으로 이 프록시를 탑니다.
// 새 라우터를 backend/routers에 추가하면(=main.py에 app.include_router 추가하면)
// 그 라우터의 최상위 경로 prefix를 아래 목록에도 추가해야 합니다.
const BACKEND_ORIGIN = "http://127.0.0.1:8000";
const BACKEND_PATH_PREFIXES = [
  "/users",
  "/companies",
  "/jobs",
  "/rag-documents",
  "/interview-sessions",
  "/interview-questions",
  "/user-answers",
  "/nonverbal-metrics",
  "/nonverbal-events",
  "/session-technical-events",
  "/session-comparisons",
  "/answer-analyses",
  "/final-coachings",
  "/ai",
  "/consents",
  "/calibration",
  "/health",
];

const proxy = {};
for (const prefix of BACKEND_PATH_PREFIXES) {
  proxy[prefix] = { target: BACKEND_ORIGIN, changeOrigin: true };
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy,
    // ngrok 등으로 터널링하면 매번 도메인이 바뀌므로(무료 플랜), 특정 호스트만
    // 허용하는 대신 전부 허용한다. 시연/개발용 설정이며, 실제 운영 배포 시에는
    // 정확한 도메인 목록으로 좁히는 것을 권장한다.
    allowedHosts: true,
  },
});
