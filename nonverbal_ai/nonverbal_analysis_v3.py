"""연진 비언어 분석 원본 실행 래퍼.

원본 `nonverbal_analysis_v3.py`가 큰 파일이라 업로드 과정에서 내용이 잘리지 않도록
`_source_parts/nonverbal_analysis_v3.part*.txt`에 원문을 순서대로 보존했다.
이 래퍼는 해당 조각들을 그대로 이어 붙여 원본 코드를 실행한다.

원본 내용 자체는 수정하지 않았다.
"""

from pathlib import Path

_PART_DIR = Path(__file__).resolve().parent / "_source_parts"
_PARTS = sorted(_PART_DIR.glob("nonverbal_analysis_v3.part*.txt"))

if not _PARTS:
    raise RuntimeError(f"비언어 분석 원본 조각을 찾을 수 없습니다: {_PART_DIR}")

_SOURCE = "".join(path.read_text(encoding="utf-8") for path in _PARTS)
exec(compile(_SOURCE, str(Path(__file__).with_name("nonverbal_analysis_v3_original.py")), "exec"), globals(), globals())
