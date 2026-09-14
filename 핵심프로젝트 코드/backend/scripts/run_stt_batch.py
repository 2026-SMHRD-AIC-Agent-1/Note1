"""45개 파일럿 영상용 상세 STT 배치 실행기.

예시:
  python scripts/run_stt_batch.py --input-root "C:/pilot/videos" --output-dir "C:/pilot/stt_results" --limit 3
  python scripts/run_stt_batch.py --input-root "C:/pilot/videos" --output-dir "C:/pilot/stt_results" --people 교민 --videos 1 2 3

입력 폴더 예시:
  videos/
    교민/video_1.mp4 ... video_9.mp4
    동원/video_1.mp4 ...

이미 결과 JSON이 있으면 기본적으로 건너뛰므로 중단 후 다시 실행해도 됩니다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from stt_service import init_stt_service, is_ready, transcribe_audio_detailed  # noqa: E402

VIDEO_RE = re.compile(r"video_(\d+)\.(?:mp4|webm|m4a|mp3|wav|mpeg|mpga)$", re.IGNORECASE)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="사람별 하위폴더가 있는 영상 루트")
    parser.add_argument("--output-dir", required=True, help="상세 STT JSON 저장 폴더")
    parser.add_argument("--people", nargs="*", help="특정 사람 폴더만 실행")
    parser.add_argument("--videos", nargs="*", type=int, help="특정 video 번호만 실행")
    parser.add_argument("--limit", type=int, default=None, help="검증용 최대 처리 개수")
    parser.add_argument("--overwrite", action="store_true", help="기존 JSON도 다시 처리")
    return parser.parse_args()


def collect_files(root: Path, people=None, videos=None):
    people_set = set(people or [])
    videos_set = set(videos or [])
    rows = []
    for path in root.glob("*/*"):
        if not path.is_file():
            continue
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


def main():
    args = parse_args()
    load_dotenv(BACKEND_DIR / ".env")
    init_stt_service()
    if not is_ready():
        raise SystemExit("STT 초기화 실패: backend/.env의 OPENAI_API_KEY를 확인하세요.")

    input_root = Path(args.input_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(input_root, args.people, args.videos)
    if args.limit is not None:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"처리할 영상이 없습니다: {input_root}")

    completed = 0
    failed = 0
    for person, video_num, path in files:
        person_dir = output_dir / person
        person_dir.mkdir(parents=True, exist_ok=True)
        out_path = person_dir / f"video_{video_num}.json"
        if out_path.exists() and not args.overwrite:
            print(f"[SKIP] {person} video_{video_num}: 이미 결과 있음")
            continue

        print(f"[STT] {person} video_{video_num} ...")
        try:
            detail = transcribe_audio_detailed(str(path))
            payload = {
                "person": person,
                "video_num": video_num,
                "source_file": path.name,
                **detail,
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"[OK] {out_path} | words={len(detail.get('words', []))} "
                f"| text={detail.get('text', '')[:60]}"
            )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            err_path = person_dir / f"video_{video_num}.error.json"
            err_path.write_text(
                json.dumps({"person": person, "video_num": video_num, "error": str(exc)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[FAIL] {person} video_{video_num}: {exc}")
            failed += 1

    print(f"완료: 성공 {completed}, 실패 {failed}, 대상 {len(files)}")


if __name__ == "__main__":
    main()
