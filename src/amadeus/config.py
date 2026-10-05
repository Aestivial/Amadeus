"""Configuration and model profile management for Amadeus.

Handles settings persistence, profile registry resolution, and model path resolution.
Settings and user profiles are stored in TOML format within the Amadeus data directory.
"""

from __future__ import annotations

import tomllib
import warnings
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field

from amadeus import paths


class ModelProfile(BaseModel):
    name: str
    description: str = ""
    repo: str | None = None  # Hugging Face repo, e.g. "Qwen/Qwen3-8B-GGUF"
    file: str | None = None  # GGUF filename inside repo
    path: str | None = None  # local GGUF path (absolute or relative to root) - overrides repo/file
    ollama: str | None = None  # Ollama tag, used when backend == "ollama"
    ctx: int = 16384
    ngl: int = 99  # GPU layers
    n_cpu_moe: int | None = None  # MoE expert layers kept on CPU
    tools: Literal["native", "text"] = "native"
    temperature: float = 0.6
    extra_args: list[str] = Field(default_factory=list)  # appended to llama-server args
    min_vram_gb: float = 0  # used by doctor for recommendations


class Settings(BaseModel):
    backend: Literal["llamacpp", "ollama", "openai"] = "llamacpp"
    openai_base_url: str = "http://127.0.0.1:8080/v1"
    ollama_url: str = "http://127.0.0.1:11434"
    default_profile: str = "general"
    mode: Literal["ask", "auto", "yolo"] = "ask"
    persona: str = "amadeus"
    banner: bool = True
    models_dir: str | None = None
    max_steps: int = 25
    memory_core_tokens: int = 1200
    web_fetch: bool = True
    shell_timeout: int = 120


def default_profile_name() -> str:
    """Return Settings.default_profile if configured by user, else models.toml top-level default."""
    user_cfg = paths.user_config_file()
    if user_cfg.is_file():
        try:
            with user_cfg.open("rb") as f:
                cfg_data = tomllib.load(f)
            if isinstance(cfg_data, dict) and "default_profile" in cfg_data:
                val = cfg_data["default_profile"]
                if isinstance(val, str) and val.strip():
                    return val.strip()
        except Exception:
            pass

    user_models = paths.user_models_file()
    if user_models.is_file():
        try:
            with user_models.open("rb") as f:
                m_data = tomllib.load(f)
            if isinstance(m_data, dict) and "default" in m_data:
                val = m_data["default"]
                if isinstance(val, str) and val.strip():
                    return val.strip()
        except Exception:
            pass

    pkg_models = paths.default_models_file()
    if pkg_models.is_file():
        try:
            with pkg_models.open("rb") as f:
                p_data = tomllib.load(f)
            if isinstance(p_data, dict) and "default" in p_data:
                val = p_data["default"]
                if isinstance(val, str) and val.strip():
                    return val.strip()
        except Exception:
            pass

    return "general"


def load_settings() -> Settings:
    """Load settings merging defaults with data/config.toml."""
    cfg_path = paths.user_config_file()
    raw_data: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            with cfg_path.open("rb") as f:
                data = tomllib.load(f)
            if isinstance(data, dict):
                raw_data = data
            else:
                warnings.warn(
                    f"User config {cfg_path} is not a valid table; falling back to defaults.",
                    UserWarning,
                    stacklevel=2,
                )
        except Exception as exc:
            warnings.warn(
                f"Failed to load user config from {cfg_path}: {exc}; falling back to defaults.",
                UserWarning,
                stacklevel=2,
            )

    if "default_profile" not in raw_data:
        raw_data["default_profile"] = default_profile_name()

    try:
        return Settings.model_validate(raw_data)
    except Exception as exc:
        warnings.warn(
            f"User config validation failed: {exc}; falling back to defaults.",
            UserWarning,
            stacklevel=2,
        )
        return Settings(default_profile=default_profile_name())


def save_setting(key: str, value: Any) -> None:
    """Validate key, coerce value via pydantic, and write to data/config.toml."""
    if key not in Settings.model_fields:
        raise KeyError(
            f"Unknown setting '{key}'. Valid settings: {sorted(Settings.model_fields.keys())}"
        )

    validated = Settings.model_validate({key: value})
    coerced = getattr(validated, key)

    cfg_path = paths.user_config_file()
    raw_config: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            with cfg_path.open("rb") as f:
                loaded = tomllib.load(f)
            if isinstance(loaded, dict):
                raw_config = loaded
        except Exception as exc:
            warnings.warn(
                f"Existing user config {cfg_path} was invalid ({exc}); resetting file.",
                UserWarning,
                stacklevel=2,
            )

    if coerced is None:
        raw_config.pop(key, None)
    else:
        raw_config[key] = coerced

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("wb") as f:
        tomli_w.dump(raw_config, f)


def load_profiles() -> dict[str, ModelProfile]:
    """Load model profiles, merging package registry with user overrides in data/models.toml."""
    profiles: dict[str, ModelProfile] = {}

    # 1. Package registry
    pkg_file = paths.default_models_file()
    if pkg_file.is_file():
        try:
            with pkg_file.open("rb") as f:
                pkg_data = tomllib.load(f)
            if isinstance(pkg_data, dict):
                pkg_profiles = pkg_data.get("profiles", {})
                if isinstance(pkg_profiles, dict):
                    for name, data in pkg_profiles.items():
                        if isinstance(data, dict):
                            p_dict = dict(data)
                            p_dict["name"] = name
                            profiles[name] = ModelProfile.model_validate(p_dict)
        except Exception as exc:
            warnings.warn(
                f"Failed to load package models from {pkg_file}: {exc}.",
                UserWarning,
                stacklevel=2,
            )

    # 2. User registry (overrides package profiles, adds new profiles)
    user_file = paths.user_models_file()
    if user_file.is_file():
        try:
            with user_file.open("rb") as f:
                user_data = tomllib.load(f)
            if isinstance(user_data, dict):
                user_profiles = user_data.get("profiles", {})
                if isinstance(user_profiles, dict):
                    for name, data in user_profiles.items():
                        if isinstance(data, dict):
                            try:
                                p_dict = dict(data)
                                p_dict["name"] = name
                                profiles[name] = ModelProfile.model_validate(p_dict)
                            except Exception as item_exc:
                                warnings.warn(
                                    f"Invalid user profile '{name}' in {user_file}: {item_exc}.",
                                    UserWarning,
                                    stacklevel=2,
                                )
        except Exception as exc:
            warnings.warn(
                f"Failed to load user models from {user_file}: {exc}; falling back to defaults.",
                UserWarning,
                stacklevel=2,
            )

    return profiles


def save_user_profile(p: ModelProfile) -> None:
    """Save or update a user model profile in data/models.toml."""
    models_path = paths.user_models_file()
    raw_data: dict[str, Any] = {}
    if models_path.is_file():
        try:
            with models_path.open("rb") as f:
                loaded = tomllib.load(f)
            if isinstance(loaded, dict):
                raw_data = loaded
        except Exception as exc:
            warnings.warn(
                f"Existing user models file {models_path} was invalid ({exc}); resetting file.",
                UserWarning,
                stacklevel=2,
            )

    profiles_table = raw_data.setdefault("profiles", {})
    if not isinstance(profiles_table, dict):
        profiles_table = {}
        raw_data["profiles"] = profiles_table

    profiles_table[p.name] = p.model_dump(exclude={"name"}, exclude_none=True)

    models_path.parent.mkdir(parents=True, exist_ok=True)
    with models_path.open("wb") as f:
        tomli_w.dump(raw_data, f)


def remove_user_profile(name: str) -> bool:
    """Remove a user model profile from data/models.toml. Returns True if found and removed."""
    models_path = paths.user_models_file()
    if not models_path.is_file():
        return False

    raw_data: dict[str, Any] = {}
    try:
        with models_path.open("rb") as f:
            loaded = tomllib.load(f)
        if isinstance(loaded, dict):
            raw_data = loaded
    except Exception as exc:
        warnings.warn(
            f"Failed to load user models from {models_path}: {exc}.",
            UserWarning,
            stacklevel=2,
        )
        return False

    profiles_table = raw_data.get("profiles")
    if not isinstance(profiles_table, dict) or name not in profiles_table:
        return False

    del profiles_table[name]

    models_path.parent.mkdir(parents=True, exist_ok=True)
    with models_path.open("wb") as f:
        tomli_w.dump(raw_data, f)
    return True


def models_dir(s: Settings) -> Path:
    """Return the configured models directory or paths.default_models_dir()."""
    if s.models_dir and s.models_dir.strip():
        p = Path(s.models_dir.strip())
        return p if p.is_absolute() else paths.root() / p
    return paths.default_models_dir()


def resolve_model_path(p: ModelProfile, s: Settings) -> Path:
    """Resolve the local file path for a model profile.

    Priority:
    1. p.path (absolute or relative to root)
    2. models_dir(s) / p.file
    """
    if p.path and p.path.strip():
        target = Path(p.path.strip())
        return target if target.is_absolute() else paths.root() / target
    if p.file and p.file.strip():
        return models_dir(s) / p.file.strip()
    raise ValueError(f"ModelProfile '{p.name}' has neither 'path' nor 'file' configured.")


__all__ = [
    "ModelProfile",
    "Settings",
    "default_profile_name",
    "load_profiles",
    "load_settings",
    "models_dir",
    "remove_user_profile",
    "resolve_model_path",
    "save_setting",
    "save_user_profile",
]
