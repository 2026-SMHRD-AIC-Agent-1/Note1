import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 백엔드 main.py의 기본 CORS_ORIGINS 값(http://localhost:3000)과 맞추기 위해
// 개발 서버 포트를 3000으로 고정합니다. 백엔드 .env의 CORS_ORIGINS를 바꾸면
// 이 값도 함께 바꿔주세요.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
  },
});
