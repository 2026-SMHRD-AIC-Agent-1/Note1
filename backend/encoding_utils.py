"""한국어 텍스트 파일의 흔한 인코딩을 공통 처리하는 유틸."""


def read_text_file(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"지원하지 않는 텍스트 인코딩: {path}")
