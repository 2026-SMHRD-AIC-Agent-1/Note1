"""프로젝트 기준의 안전한 파일/환경변수 경로 해석."""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent


def resolve_project_path(value: str | None, default_relative: str) -> Path:
    raw = value or default_relative
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_database_url(value: str | None) -> str:
    url = value or "sqlite:///./app.db"
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith("sqlite:////"):
        raw = url[len(prefix):]
        path = Path(raw)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return f"sqlite:///{path.as_posix()}"
    return url
