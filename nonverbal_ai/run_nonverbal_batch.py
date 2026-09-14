"""45개 파일럿 영상용 비언어 + 기존 STT 통합 배치 실행기.

- 영상에서 ffmpeg로 16kHz mono WAV를 추출합니다.
- 기존 STT JSON의 text/word timestamp를 재사용합니다. (STT API 재호출 없음)
- nonverbal_analysis_v3.analyze_video()를 실행합니다.
- stability_features.derive_stability_features()로 측정상태/정규화 지표를 함께 저장합니다.
- 오디오 이상은 0점으로 바꾸지 않고 measurement_unavailable 상태를 보존합니다.

예시:
  python run_nonverbal_batch.py --input-root "C:/pilot/videos" --stt-root "C:/pilot/stt_results" --audio-root "C:/pilot/audio" --output-dir "C:/pilot/nonverbal_results" --people 교민 --videos 1
  python run_nonverbal_batch.py --input-root "C:/pilot/videos" --stt-root "C:/pilot/stt_results" --audio-root "C:/pilot/audio" --output-dir "C:/pilot/nonverbal_results"
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path

import nonverbal_analysis_v3 as nonverbal
from stability_features import derive_stability_features

VIDEO_RE = re.compile(r"video_(\d+)\.mp4$", re.IGNORECASE)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="사람별 하위폴더가 있는 영상 루트")
    parser.add_argument("--stt-root", required=True, help="기존 상세 STT JSON 루트")
    parser.add_argument("--audio-root", required=True, help="추출 WAV 저장 루트")
    parser.add_argument("--output-dir", required=True, help="통합 비언어 결과 JSON 저장 루트")
    parser.add_argument("--people", nargs="*", help="특정 사람 폴더만 실행")
    parser.add_argument("--videos", nargs="*", type=int, help="특정 video 번호만 실행")
    parser.add_argument("--limit", type=int, default=None, help="검증용 최대 처리 개수")
    parser.add_argument("--overwrite", action="store_true", help="기존 WAV/결과 JSON도 다시 생성")
    return parser.parse_args()


def collect_files(root: Path, people=None, videos=None):
    people_set = set(people or [])
    videos_set = set(videos or [])
    rows = []
    for path in root.glob("*/*.mp4"):
        m = VIDEO_RE.fullmatch(path.name)
        if not m:
            continue
        person = path.parent.name
        video_num = int(m.group(1))
        if people_set and person not in people_set:
            continue
        if videos_set and video_num not in videos_set:
            continue
        rows.append((person, video_num, path))
    return sorted(rows, key=lambda x: (x[0], x[1]))


def ensure_wav(video_path: Path, wav_path: Path, overwrite: bool = False):
    if wav_path.exists() and not overwrite:
        return
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(wav_path),
    ]
    subprocess.run(cmd, check=True)


def load_stt(stt_path: Path):
    if not stt_path.exists():
        raise FileNotFoundError(f"STT JSON 없음: {stt_path}")
    payload = json.loads(stt_path.read_text(encoding="utf-8"))
    word_timestamps = []
    for item in payload.get("words", []) or []:
        start = item.get("start")
        if start is None:
            continue
        word_timestamps.append((item.get("word", ""), float(start)))
    return payload, word_timestamps


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"JSON 직렬화 불가 타입: {type(value).__name__}")


def main():
    args = parse_args()

    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg를 찾을 수 없습니다. 새 터미널에서 ffmpeg -version을 확인하세요.")

    input_root = Path(args.input_root).expanduser().resolve()
    stt_root = Path(args.stt_root).expanduser().resolve()
    audio_root = Path(args.audio_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(input_root, args.people, args.videos)
    if args.limit is not None:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"처리할 영상이 없습니다: {input_root}")

    completed = 0
    failed = 0
    unavailable_audio = 0

    for person, video_num, video_path in files:
        person_out = output_dir / person
        person_out.mkdir(parents=True, exist_ok=True)
        out_path = person_out / f"video_{video_num}.json"
        err_path = person_out / f"video_{video_num}.error.json"

        if out_path.exists() and not args.overwrite:
            print(f"[SKIP] {person} video_{video_num}: 이미 결과 있음")
            continue

        wav_path = audio_root / person / f"video_{video_num}.wav"
        stt_path = stt_root / person / f"video_{video_num}.json"

        print(f"[ANALYZE] {person} video_{video_num} ...")
        try:
            ensure_wav(video_path, wav_path, overwrite=args.overwrite)
            stt_payload, word_timestamps = load_stt(stt_path)

            raw = nonverbal.analyze_video(
                str(video_path),
                audio_path=str(wav_path),
                stt_text=stt_payload.get("text", ""),
                word_timestamps=word_timestamps,
            )

            duration_sec = stt_payload.get("duration_sec")
            features = derive_stability_features(raw, duration_sec=duration_sec)
            audio_status = features.get("measurement", {}).get("audio_status")
            if audio_status == "measurement_unavailable":
                unavailable_audio += 1

            payload = {
                "person": person,
                "video_num": video_num,
                "source_file": video_path.name,
                "audio_file": str(wav_path),
                "stt_source_file": str(stt_path),
                "stt_text": stt_payload.get("text", ""),
                "stt_duration_sec": duration_sec,
                "raw_nonverbal": raw,
                "stability_features": features,
            }
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
                encoding="utf-8",
            )
            if err_path.exists():
                err_path.unlink()

            gaze_status = features.get("measurement", {}).get("gaze_status")
            print(f"[OK] {person} video_{video_num} | audio={audio_status} | gaze={gaze_status}")
            completed += 1
        except Exception as exc:  # noqa: BLE001
            err_payload = {
                "person": person,
                "video_num": video_num,
                "source_file": video_path.name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            err_path.write_text(
                json.dumps(err_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[FAIL] {person} video_{video_num}: {type(exc).__name__}: {exc}")
            failed += 1

    print(
        f"완료: 성공 {completed}, 실패 {failed}, 대상 {len(files)}, "
        f"오디오 측정불가 {unavailable_audio}"
    )


if __name__ == "__main__":
    main()
