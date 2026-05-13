from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    env_root = os.getenv("PEPPA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (
            (candidate / "config.toml").exists()
            or (candidate / "config.example.toml").exists()
            or (candidate / "pyproject.toml").exists()
        ):
            return candidate

    return Path(__file__).resolve().parents[2]


ROOT_DIR = project_root()
CONFIG_PATH = ROOT_DIR / "config.toml"
CONFIG_EXAMPLE_PATH = ROOT_DIR / "config.example.toml"
STATE_DIR = ROOT_DIR / "state"
DATABASE_PATH = STATE_DIR / "peppa.sqlite3"
VAR_DIR = ROOT_DIR / "var"
LOG_DIR = VAR_DIR / "logs"
TRACE_DIR = VAR_DIR / "traces"
CACHE_DIR = VAR_DIR / "cache"
RUNTIME_DIR = VAR_DIR / "runtime"
WEB_DIST_DIR = ROOT_DIR / "web" / "dist"


def ensure_runtime_dirs() -> None:
    for path in (STATE_DIR, LOG_DIR, TRACE_DIR, CACHE_DIR, RUNTIME_DIR):
        path.mkdir(parents=True, exist_ok=True)
