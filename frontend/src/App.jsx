import { useEffect, useState } from "react";
import TopBar from "./components/TopBar.jsx";
import LandingPage from "./pages/LandingPage.jsx";
import EntryPage from "./pages/EntryPage.jsx";
import SetupPage from "./pages/SetupPage.jsx";
import CalibrationPage from "./pages/CalibrationPage.jsx";
import InterviewPage from "./pages/InterviewPage.jsx";
import ReportPage from "./pages/ReportPage.jsx";
import { health } from "./api.js";

export default function App() {
  const [view, setView] = useState("landing");
  const [backendStatus, setBackendStatus] = useState("checking"); // checking | ok | down

  const [user, setUser] = useState(null);
  const [session, setSession] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [coaching, setCoaching] = useState(null);

  useEffect(() => {
    health()
      .then(() => setBackendStatus("ok"))
      .catch(() => setBackendStatus("down"));
  }, []);

  const stepIndex = { landing: -1, entry: 0, setup: 1, calibration: 1, interview: 2, report: 3 }[view];

  return (
    <div>
      {view !== "landing" && <TopBar current={stepIndex} />}
      <div>
        {backendStatus === "down" && view !== "landing" && (
          <div className="notice notice-error" style={{ margin: "16px 40px 0" }}>
            백엔드({import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000"})에 연결할 수
            없습니다. FastAPI 서버(uvicorn main:app --reload)가 실행 중인지, .env의
            VITE_API_BASE 값이 맞는지 확인해주세요.
          </div>
        )}

        {view === "landing" && <LandingPage onStart={() => setView("entry")} />}

        {view === "entry" && (
          <EntryPage
            onReady={(u) => {
              setUser(u);
              setView("setup");
            }}
          />
        )}

        {view === "setup" && user && (
          <SetupPage
            user={user}
            onReady={({ session, questions }) => {
              setSession(session);
              setQuestions(questions);
              setAnswers({});
              setCoaching(null);
              setView("calibration");
            }}
          />
        )}

        {view === "calibration" && session && (
          <CalibrationPage
            session={session}
            onPassed={() => setView("interview")}
          />
        )}

        {view === "interview" && session && questions.length > 0 && (
          <InterviewPage
            user={user}
            session={session}
            questions={questions}
            onFinish={({ questions, answers, coaching }) => {
              setQuestions(questions);
              setAnswers(answers);
              setCoaching(coaching);
              setView("report");
            }}
          />
        )}

        {view === "report" && session && coaching && (
          <ReportPage
            user={user}
            session={session}
            questions={questions}
            answers={answers}
            coaching={coaching}
            onStartNextRound={({ session, questions }) => {
              setSession(session);
              setQuestions(questions);
              setAnswers({});
              setCoaching(null);
              setView("calibration");
            }}
          />
        )}
      </div>
    </div>
  );
}
