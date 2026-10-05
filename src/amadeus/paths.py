"""All filesystem locations used by Amadeus.

Every path is resolved relative to the install root so the whole project is
self-contained and portable. Nothing is written to the user's home / AppData.
Use the functions (not cached constants) so tests can override AMADEUS_HOME.
"""

from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    env = os.environ.get("AMADEUS_HOME")
    if env:
        return Path(env).resolve()
    # src/amadeus/paths.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def assets_dir() -> Path:
    return root() / "assets"


def runtime_dir() -> Path:
    return root() / ".runtime"


def bin_dir() -> Path:
    return root() / "bin"


def llamacpp_dir() -> Path:
    return bin_dir() / "llama.cpp"


def data_dir() -> Path:
    return root() / "data"


def default_models_dir() -> Path:
    return root() / "models"


def memory_dir() -> Path:
    return data_dir() / "memory"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


def logs_dir() -> Path:
    return data_dir() / "logs"


def user_config_file() -> Path:
    return data_dir() / "config.toml"


def user_models_file() -> Path:
    return data_dir() / "models.toml"


def default_models_file() -> Path:
    return package_dir() / "models.toml"


def persona_dir() -> Path:
    return package_dir() / "persona"


def history_file() -> Path:
    return data_dir() / "history.txt"


def ensure_dirs() -> None:
    for d in (data_dir(), memory_dir(), memory_dir() / "notes", sessions_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)


def is_within(path: Path, base: Path) -> bool:
    """True if `path` resolves inside `base`."""
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False
