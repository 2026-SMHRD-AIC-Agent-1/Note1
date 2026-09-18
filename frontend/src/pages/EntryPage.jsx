import { useState } from "react";
import { ShieldCheck, Mail, User, ArrowRight } from "lucide-react";
import { createUser, createConsent, listUsers } from "../api.js";

// 간단한 해시 대체값. 이 프로젝트는 로그인 화면/인증 로직이 없는 MVP이므로
// 실제 비밀번호를 받지 않고, users.password_hash 컬럼(NOT NULL)을 채우기 위한
// 더미 값만 생성합니다. 실제 서비스라면 별도 회원가입/인증 흐름이 필요합니다.
function makeDummyHash() {
  return `mvp-${Math.random().toString(36).slice(2)}${Date.now()}`;
}

// 이 4가지는 백엔드 routers/consents.py의 VALID_CONSENT_TYPES와
// 정확히 일치해야 합니다 (다른 문자열을 보내면 400 에러). uploads.py가
// 답변 제출 시 AUDIO_RECORDING·VIDEO_RECORDING·ANALYSIS 동의를 각각
// 실시간으로 확인하기 때문에, 화면에서는 체크박스 하나로 묶어 보여주더라도
// 내부적으로는 이 4건을 모두 기록합니다.
const REQUIRED_CONSENT_TYPES = ["AUDIO_RECORDING", "VIDEO_RECORDING", "ANALYSIS", "DATA_RETENTION"];

async function grantAllConsents(userId) {
  for (const consent_type of REQUIRED_CONSENT_TYPES) {
    await createConsent({
      user_id: userId,
      consent_type,
      is_agreed: true,
      policy_version: "mvp-v1",
    });
  }
}

export default function EntryPage({ onReady }) {
  const [step, setStep] = useState("email"); // email | new | returning
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const [foundUser, setFoundUser] = useState(null);
  const [checking, setChecking] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // 별도의 "이메일로 사용자 조회" API가 없어서, 사용자 목록(GET /users)에서
  // 이메일이 일치하는 계정이 있는지 확인합니다. 있으면 그 계정을 그대로 쓰고,
  // 없으면 새로 만듭니다 — 매번 새 이름/이메일을 요구하지 않기 위함입니다.
  async function handleCheckEmail(e) {
    e.preventDefault();
    if (!email.trim()) return;
    setChecking(true);
    setError(null);
    try {
      const users = await listUsers();
      const match = users.find(
        (u) => u.email.toLowerCase() === email.trim().toLowerCase()
      );
      if (match) {
        setFoundUser(match);
        setStep("returning");
      } else {
        setStep("new");
      }
    } catch (err) {
      setError(err.message || "사용자 확인에 실패했습니다.");
    } finally {
      setChecking(false);
    }
  }

  async function handleContinueNew(e) {
    e.preventDefault();
    if (!name.trim() || !agree) return;
    setLoading(true);
    setError(null);
    try {
      const user = await createUser({
        email: email.trim(),
        password_hash: makeDummyHash(),
        name: name.trim(),
      });
      await grantAllConsents(user.user_id);
      onReady(user);
    } catch (err) {
      setError(err.message || "사용자 정보를 저장하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function handleContinueReturning(e) {
    e.preventDefault();
    if (!agree || !foundUser) return;
    setLoading(true);
    setError(null);
    try {
      await grantAllConsents(foundUser.user_id);
      onReady(foundUser);
    } catch (err) {
      setError(err.message || "동의 정보를 저장하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  function handleUseDifferentEmail() {
    setStep("email");
    setFoundUser(null);
    setName("");
    setAgree(false);
    setError(null);
  }

  const consentBlock = (
    <>
      <p style={{ fontSize: 13.5 }}>
        면접 중 촬영되는 영상과 음성은 답변 STT 변환, 내용·비언어 분석, 코칭 리포트 생성에만
        사용되며, 합격 가능성 판정이나 성격·감정 추정에는 사용되지 않습니다.
      </p>
      <label className="checkbox-row">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span>개인정보 및 신체정보(영상/음성) 수집 및 이용에 동의합니다.</span>
      </label>
    </>
  );

  return (
    <div className="main">
      <div className="auth-card-wrap">
        <div className="auth-icon">
          <ShieldCheck size={26} />
        </div>
        <h1 style={{ fontSize: 22 }}>AI 모의면접 서비스 동의</h1>
        <p className="lede" style={{ margin: "0 auto 22px" }}>
          원활한 면접 진행과 분석 리포트 생성을 위해 계정 확인과 동의가 필요합니다.
        </p>

        <div className="panel">
          {step === "email" && (
            <form onSubmit={handleCheckEmail}>
              <div className="field">
                <label htmlFor="email" className="icon-label">
                  <Mail size={15} /> 이메일
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoFocus
                />
              </div>
              {error && <div className="notice notice-error">{error}</div>}
              <button className="btn btn-primary btn-block" type="submit" disabled={checking}>
                {checking && <span className="spinner" />}
                다음 <ArrowRight size={15} />
              </button>
            </form>
          )}

          {step === "returning" && (
            <form onSubmit={handleContinueReturning}>
              <div className="notice notice-info">
                다시 오셨네요, {foundUser.name}님! ({email})
              </div>
              {consentBlock}
              {error && <div className="notice notice-error">{error}</div>}
              <button className="btn btn-primary btn-block" type="submit" disabled={!agree || loading}>
                {loading && <span className="spinner" />}
                동의하고 계속하기
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-block"
                style={{ marginTop: 10, fontSize: 13 }}
                onClick={handleUseDifferentEmail}
              >
                다른 이메일로 시작하기
              </button>
            </form>
          )}

          {step === "new" && (
            <form onSubmit={handleContinueNew}>
              <div className="notice notice-info">
                {email}로 등록된 계정이 없어서 새로 만듭니다.
              </div>
              <div className="field">
                <label htmlFor="name" className="icon-label">
                  <User size={15} /> 이름
                </label>
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="홍길동"
                  required
                  autoFocus
                />
              </div>
              {consentBlock}
              {error && <div className="notice notice-error">{error}</div>}
              <button
                className="btn btn-primary btn-block"
                type="submit"
                disabled={!name.trim() || !agree || loading}
              >
                {loading && <span className="spinner" />}
                동의하고 시작하기
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-block"
                style={{ marginTop: 10, fontSize: 13 }}
                onClick={handleUseDifferentEmail}
              >
                다른 이메일로 시작하기
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
