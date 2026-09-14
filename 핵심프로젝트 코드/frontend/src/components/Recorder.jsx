import { useEffect, useRef, useState } from "react";
import { Camera, Circle, Square, CheckCircle2 } from "lucide-react";

// 백엔드 POST /user-answers/submit 은 audio(필수)와 video(선택)를 분리된
// 파일로 받습니다 (media_service.py ALLOWED_AUDIO_TYPES / ALLOWED_VIDEO_TYPES).
// 브라우저 MediaRecorder는 하나의 스트림을 한 번에 하나의 컨테이너로만
// 기록하므로, 오디오 트랙만 뽑은 별도 스트림 하나 + 오디오+비디오 전체
// 스트림 하나, 총 두 개의 MediaRecorder를 동시에 돌려서 두 파일을 만듭니다.
export default function Recorder({ onRecorded, disabled }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const videoRecorderRef = useRef(null);
  const audioRecorderRef = useRef(null);
  const videoChunksRef = useRef([]);
  const audioChunksRef = useRef([]);

  const [permissionState, setPermissionState] = useState("idle"); // idle | granted | denied
  const [isRecording, setIsRecording] = useState(false);
  const [hasRecording, setHasRecording] = useState(false);
  const [error, setError] = useState(null);
  const recordingStartedAtRef = useRef(null);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function enableCamera() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setPermissionState("granted");
    } catch (err) {
      // FR-AI-010: 마이크/카메라 권한이 없으면 세션 진행을 제한합니다.
      setPermissionState("denied");
      setError(
        "카메라·마이크 권한이 없어 녹화를 시작할 수 없습니다. 브라우저 권한을 허용한 뒤 다시 시도해주세요."
      );
    }
  }

  function pickMimeType(candidates) {
    return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || "";
  }

  function startRecording() {
    const stream = streamRef.current;
    if (!stream) return;
    setError(null);
    videoChunksRef.current = [];
    audioChunksRef.current = [];
    setHasRecording(false);

    const videoMime = pickMimeType(["video/webm;codecs=vp9,opus", "video/webm"]);
    const audioMime = pickMimeType(["audio/webm;codecs=opus", "audio/webm"]);

    try {
      const videoRecorder = new MediaRecorder(stream, videoMime ? { mimeType: videoMime } : undefined);
      videoRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) videoChunksRef.current.push(e.data);
      };
      videoRecorderRef.current = videoRecorder;

      const audioOnlyStream = new MediaStream(stream.getAudioTracks());
      const audioRecorder = new MediaRecorder(
        audioOnlyStream,
        audioMime ? { mimeType: audioMime } : undefined
      );
      audioRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      audioRecorderRef.current = audioRecorder;

      videoRecorder.start();
      audioRecorder.start();
      recordingStartedAtRef.current = Date.now();
      setIsRecording(true);
    } catch (err) {
      setError(`녹화를 시작하지 못했습니다: ${err.message}`);
    }
  }

  function stopRecording() {
    const videoRecorder = videoRecorderRef.current;
    const audioRecorder = audioRecorderRef.current;
    if (!videoRecorder || !audioRecorder) return;

    let stopped = 0;
    const startedAt = recordingStartedAtRef.current;
    const onEachStop = () => {
      stopped += 1;
      if (stopped === 2) {
        // 백엔드는 Content-Type을 "audio/webm"·"video/webm"처럼 코덱 정보
        // 없는 기본 타입으로만 허용합니다. MediaRecorder.mimeType은 보통
        // "audio/webm;codecs=opus"처럼 코덱이 붙어서 나오므로, 세미콜론
        // 뒤를 잘라내고 기본 타입만 Blob에 지정합니다 (실제 데이터는 그대로
        // 유효한 webm/opus이고, 선언하는 Content-Type만 맞춰주는 것입니다).
        const baseMime = (mime) => (mime || "").split(";")[0].trim();
        const videoBlob = new Blob(videoChunksRef.current, {
          type: baseMime(videoRecorder.mimeType) || "video/webm",
        });
        const audioBlob = new Blob(audioChunksRef.current, {
          type: baseMime(audioRecorder.mimeType) || "audio/webm",
        });
        const durationSec = startedAt ? Math.round((Date.now() - startedAt) / 1000) : undefined;
        setHasRecording(true);
        onRecorded({ audioBlob, videoBlob, durationSec });
      }
    };
    videoRecorder.onstop = onEachStop;
    audioRecorder.onstop = onEachStop;
    videoRecorder.stop();
    audioRecorder.stop();
    setIsRecording(false);
  }

  return (
    <div>
      <div className="recorder-frame">
        <video ref={videoRef} autoPlay muted playsInline />
        {isRecording && (
          <span className="rec-dot">
            <span className="dot" /> 녹화 중
          </span>
        )}
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      <div className="btn-row">
        {permissionState !== "granted" && (
          <button className="btn btn-primary" onClick={enableCamera} disabled={disabled}>
            <Camera size={15} /> 카메라·마이크 켜기
          </button>
        )}
        {permissionState === "granted" && !isRecording && (
          <button className="btn btn-accent" onClick={startRecording} disabled={disabled}>
            <Circle size={13} fill="currentColor" /> 답변 녹화 시작
          </button>
        )}
        {isRecording && (
          <button className="btn btn-danger" onClick={stopRecording}>
            <Square size={13} fill="currentColor" /> 녹화 중지
          </button>
        )}
        {hasRecording && !isRecording && (
          <span className="tag" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <CheckCircle2 size={13} /> 녹화 완료 — 아래에서 답변을 제출하세요
          </span>
        )}
      </div>
    </div>
  );
}
