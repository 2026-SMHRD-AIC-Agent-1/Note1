import { useEffect, useRef, useState } from "react";
import { Camera, CheckCircle2, RotateCcw, AlertTriangle } from "lucide-react";
import { submitCalibration } from "../api.js";

// 통합 규격 V1의 안내 문장(calibration_policy_v1.AUDIO_SCRIPT_TEXT)과 동일합니다.
const SCRIPT_TEXT = "안녕하세요. 지금부터 면접을 시작하겠습니다.";
const RECORD_SECONDS = 5;

// 통합 규격 V1(9. 캘리브레이션 실패 코드)의 안내 문구.
const FAILURE_MESSAGES = {
  FACE_NOT_FULLY_VISIBLE: "얼굴 전체가 화면 안에 들어오도록 위치를 조정해주세요.",
  EYES_NOT_BOTH_VISIBLE: "양쪽 눈이 모두 보이도록 위치를 조정해주세요.",
  SHOULDERS_NOT_BOTH_VISIBLE: "양쪽 어깨가 모두 보이도록 카메라에서 조금 더 멀어져주세요.",
  VISUAL_DETECTION_LOW: "얼굴/자세가 화면에 충분히 잡히지 않았어요. 조명을 밝게 하고 다시 시도해주세요.",
  VISUAL_NOT_STABLE: "촬영 중 움직임이 감지됐어요. 3초간 자세를 유지해주세요.",
  MIC_SILENT: "마이크 소리가 거의 감지되지 않았어요. 마이크 연결과 음소거 여부를 확인해주세요.",
  TOO_NOISY: "주변 소음이 큰 것 같아요. 조용한 곳에서 다시 시도해주세요.",
  LOW_SNR: "목소리와 배경 소음이 잘 구분되지 않아요. 마이크에 더 가까이서 말해주세요.",
  CAMERA_PERMISSION_DENIED: "카메라 권한이 꺼져 있어요. 브라우저 권한을 허용해주세요.",
  MIC_PERMISSION_DENIED: "마이크 권한이 꺼져 있어요. 브라우저 권한을 허용해주세요.",
  CAMERA_ERROR: "카메라를 불러오지 못했어요. 다른 프로그램이 카메라를 사용 중인지 확인해주세요.",
  FRAME_READ_ERROR: "영상을 읽는 중 문제가 발생했어요. 다시 시도해주세요.",
  AUDIO_CAPTURE_ERROR: "음성을 읽는 중 문제가 발생했어요. 다시 시도해주세요.",
  VISUAL_CALIBRATION_FAILED: "시각 캘리브레이션에 실패했어요. 다시 시도해주세요.",
  AUDIO_CALIBRATION_FAILED: "음성 캘리브레이션에 실패했어요. 다시 시도해주세요.",
};

export default function CalibrationPage({ session, onPassed }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);

  const [permissionState, setPermissionState] = useState("idle"); // idle | granted | denied
  const [phase, setPhase] = useState("ready"); // ready | countdown | recording | submitting | passed | failed | error
  const [countdown, setCountdown] = useState(3);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function enableCamera() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { frameRate: { ideal: 30, min: 24 }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: true,
      });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setPermissionState("granted");
    } catch (err) {
      setPermissionState("denied");
      // 브라우저 권한이 꺼진 경우(NotAllowedError)와, 카메라가 다른 곳에서
      // 이미 사용 중이거나(NotReadableError) 장치를 못 찾는 경우(NotFoundError)는
      // 원인이 다르므로 실제 에러 이름을 구분해서 보여준다.
      if (err.name === "NotReadableError" || err.name === "TrackStartError") {
        setError("카메라 또는 마이크를 다른 프로그램(다른 탭, Zoom, Teams 등)에서 이미 사용 중인 것 같아요. 다른 곳에서 카메라를 쓰고 있다면 닫고 다시 시도해주세요.");
      } else if (err.name === "NotFoundError" || err.name === "OverconstrainedError") {
        setError("카메라 또는 마이크 장치를 찾을 수 없어요. 장치가 제대로 연결되어 있는지 확인해주세요.");
      } else if (err.name === "NotAllowedError" || err.name === "SecurityError") {
        setError(FAILURE_MESSAGES.CAMERA_PERMISSION_DENIED);
      } else {
        setError(`카메라를 켜지 못했습니다 (${err.name || "알 수 없는 오류"}): ${err.message || ""}`);
      }
    }
  }

  function pickMimeType() {
    const candidates = ["video/webm;codecs=vp9,opus", "video/webm"];
    return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || "";
  }

  function startCountdownThenRecord() {
    setError(null);
    setResult(null);
    setPhase("countdown");
    let remaining = 3;
    setCountdown(remaining);
    const timer = setInterval(() => {
      remaining -= 1;
      setCountdown(remaining);
      if (remaining <= 0) {
        clearInterval(timer);
        beginRecording();
      }
    }, 1000);
  }

  function beginRecording() {
    const stream = streamRef.current;
    if (!stream) return;
    chunksRef.current = [];
    const mime = pickMimeType();
    try {
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = handleRecordingComplete;
      recorderRef.current = recorder;
      recorder.start();
      setPhase("recording");
      setTimeout(() => {
        if (recorderRef.current && recorderRef.current.state !== "inactive") {
          recorderRef.current.stop();
        }
      }, RECORD_SECONDS * 1000);
    } catch (err) {
      setPhase("error");
      setError(`녹화를 시작하지 못했습니다: ${err.message}`);
    }
  }

  async function handleRecordingComplete() {
    const baseMime = (recorderRef.current?.mimeType || "video/webm").split(";")[0].trim();
    const videoBlob = new Blob(chunksRef.current, { type: baseMime || "video/webm" });
    setPhase("submitting");
    try {
      const response = await submitCalibration({
        session_id: session.session_id,
        videoBlob,
        durationSec: RECORD_SECONDS,
      });
      setResult(response);
      if (response.calibration_status === "passed") {
        setPhase("passed");
      } else {
        setPhase("failed");
      }
    } catch (err) {
      setPhase("error");
      setError(err.message || "캘리브레이션 판정 요청에 실패했습니다.");
    }
  }

  function retry() {
    setResult(null);
    setError(null);
    setPhase("ready");
  }

  return (
    <div className="main" style={{ maxWidth: 720 }}>
      <div className="eyebrow">면접 전 캘리브레이션</div>
      <h1>카메라·마이크 상태를 확인할게요</h1>
      <p style={{ marginTop: -6, marginBottom: 20 }}>
        화면 중앙을 보면서 3초간 자세를 유지하고, 이어서 아래 문장을 소리 내어 읽어주세요.
        이 기준값은 면접이 끝날 때까지 그대로 사용되며, 중간에 다시 캘리브레이션하지 않습니다.
      </p>

      <div className="panel">
        <div className="recorder-frame" style={{ position: "relative" }}>
          <video ref={videoRef} autoPlay muted playsInline />
          {phase === "countdown" && (
            <div
              style={{
                position: "absolute", inset: 0, display: "flex", alignItems: "center",
                justifyContent: "center", fontSize: 48, fontWeight: 700, color: "#fff",
                background: "rgba(0,0,0,0.35)",
              }}
            >
              {countdown > 0 ? countdown : "시작!"}
            </div>
          )}
          {phase === "recording" && (
            <span className="rec-dot">
              <span className="dot" /> 녹화 중 — 아래 문장을 읽어주세요
            </span>
          )}
        </div>

        <div className="panel-title" style={{ marginTop: 14 }}>읽어주실 문장</div>
        <p style={{ fontSize: 16, fontWeight: 600 }}>&ldquo;{SCRIPT_TEXT}&rdquo;</p>

        {error && (
          <div className="notice notice-error" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <AlertTriangle size={16} style={{ marginTop: 2 }} />
            <span>{error}</span>
          </div>
        )}

        {phase === "failed" && result && (
          <div className="notice notice-error">
            <strong>캘리브레이션을 통과하지 못했어요</strong>
            <ul style={{ marginTop: 6 }}>
              {(result.failure_reasons || []).map((code) => (
                <li key={code}>{FAILURE_MESSAGES[code] || code}</li>
              ))}
              {(result.failure_reasons || []).length === 0 && !result.technical_error && (
                <li>알 수 없는 이유로 실패했습니다. 다시 시도해주세요.</li>
              )}
            </ul>
            {result.technical_error && (
              <p style={{ marginTop: 8, fontSize: 12.5, fontFamily: "monospace", whiteSpace: "pre-wrap" }}>
                기술적 오류(개발자용): {result.technical_error}
              </p>
            )}
          </div>
        )}

        {phase === "passed" && (
          <div className="notice" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <CheckCircle2 size={16} /> 캘리브레이션을 통과했어요. 이제 면접을 시작할 수 있습니다.
          </div>
        )}

        <div className="btn-row" style={{ marginTop: 14 }}>
          {permissionState !== "granted" && (
            <button className="btn btn-primary" onClick={enableCamera}>
              <Camera size={15} /> 카메라·마이크 켜기
            </button>
          )}
          {permissionState === "granted" && (phase === "ready" || phase === "error") && (
            <button className="btn btn-accent" onClick={startCountdownThenRecord}>
              캘리브레이션 시작 (3초 유지 + 문장 읽기)
            </button>
          )}
          {phase === "submitting" && <span className="tag">판정 중…</span>}
          {phase === "failed" && (
            <button className="btn btn-accent" onClick={retry}>
              <RotateCcw size={15} /> 다시 시도
            </button>
          )}
          {phase === "passed" && (
            <button className="btn btn-primary" onClick={onPassed}>
              면접 시작하기
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
