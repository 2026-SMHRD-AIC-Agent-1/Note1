"""연진 비언어 분석 원본 실행 래퍼.

원본 `nonverbal_analysis_v3.py`가 큰 파일이라 업로드 과정에서 내용이 잘리지 않도록
`_source_parts/nonverbal_analysis_v3.part*.txt`에 원문을 순서대로 보존했다.
이 래퍼는 해당 조각들을 이어 붙여 원본 코드를 실행한다.

업로드 전 원본 SHA-256:
623216ae2a2a814691e3401051f3ff730b0383052d03e6459cd6928b00a7a970
"""

from pathlib import Path
import hashlib

_PART_DIR = Path(__file__).resolve().parent / "_source_parts"
_PARTS = sorted(_PART_DIR.glob("nonverbal_analysis_v3.part*.txt"))

if not _PARTS:
    raise RuntimeError(f"비언어 분석 원본 조각을 찾을 수 없습니다: {_PART_DIR}")

_SOURCE = "".join(path.read_text(encoding="utf-8") for path in _PARTS)

# 커넥터로 큰 원문을 분할 업로드하는 과정에서 part01 끝에 중복된 경계 블록이 들어간 것을
# 실행 시 제거해, 연진이가 전달한 원본과 동일한 소스로 복원한다.
_TRANSFER_ARTIFACT = """        shoulder_width_baseline=median(pose_series.shoulder_width),\n        shoulder_angle_baseline=circular_mean_degrees(pose_series.shoulder_angle),\n        is_valid=is_valid,\n        validation_message=validation_message,\n        detection_rate=detection_rate,\n    )\n"""
_SOURCE = _SOURCE.replace(_TRANSFER_ARTIFACT, "", 1)

_EXPECTED_SHA256 = "623216ae2a2a814691e3401051f3ff730b0383052d03e6459cd6928b00a7a970"
_actual_sha256 = hashlib.sha256(_SOURCE.encode("utf-8")).hexdigest()
if _actual_sha256 != _EXPECTED_SHA256:
    raise RuntimeError(
        "비언어 분석 원본 조각의 무결성 검증에 실패했습니다. "
        f"expected={_EXPECTED_SHA256}, actual={_actual_sha256}"
    )

exec(compile(_SOURCE, str(Path(__file__).with_name("nonverbal_analysis_v3_original.py")), "exec"), globals(), globals())

# 45개 파일럿 검토에서 확인된 계산 오류는 원본 보존과 분리해 런타임 패치로 적용한다.
_PATCH_FILE = Path(__file__).resolve().parent / "runtime_patches.py"
if _PATCH_FILE.exists():
    _PATCH_SOURCE = _PATCH_FILE.read_text(encoding="utf-8")
    exec(compile(_PATCH_SOURCE, str(_PATCH_FILE), "exec"), globals(), globals())
