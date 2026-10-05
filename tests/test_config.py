from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from amadeus import paths
from amadeus.config import (
    ModelProfile,
    Settings,
    default_profile_name,
    load_profiles,
    load_settings,
    models_dir,
    remove_user_profile,
    resolve_model_path,
    save_setting,
    save_user_profile,
)


def test_settings_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    s = load_settings()
    assert s.backend == "llamacpp"
    assert s.openai_base_url == "http://127.0.0.1:8080/v1"
    assert s.ollama_url == "http://127.0.0.1:11434"
    assert s.default_profile == "general"
    assert s.mode == "ask"
    assert s.persona == "amadeus"
    assert s.banner is True
    assert s.models_dir is None
    assert s.max_steps == 25
    assert s.memory_core_tokens == 1200
    assert s.web_fetch is True
    assert s.shell_timeout == 120

    assert default_profile_name() == "general"


def test_package_profiles_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    profiles = load_profiles()
    assert "general" in profiles
    assert "power" in profiles
    assert "coder" in profiles
    assert "lite" in profiles

    general = profiles["general"]
    assert general.name == "general"
    assert general.repo == "Qwen/Qwen3-8B-GGUF"
    assert general.file == "Qwen3-8B-Q4_K_M.gguf"
    assert general.ctx == 16384
    assert general.min_vram_gb == 6.0
    assert general.ollama == "qwen3:8b"

    power = profiles["power"]
    assert power.name == "power"
    assert power.repo == "Qwen/Qwen3-30B-A3B-GGUF"
    assert power.file == "Qwen3-30B-A3B-Q4_K_M.gguf"
    assert power.n_cpu_moe == 30
    assert power.ctx == 16384
    assert power.min_vram_gb == 6.0
    assert power.ollama == "qwen3:30b"

    coder = profiles["coder"]
    assert coder.name == "coder"
    assert coder.repo == "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
    assert coder.file == "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
    assert coder.min_vram_gb == 6.0
    assert coder.ollama == "qwen2.5-coder:7b"

    lite = profiles["lite"]
    assert lite.name == "lite"
    assert lite.repo == "Qwen/Qwen3-4B-GGUF"
    assert lite.file == "Qwen3-4B-Q4_K_M.gguf"
    assert lite.ctx == 8192
    assert lite.min_vram_gb == 3.0
    assert lite.ollama == "qwen3:4b"


def test_user_settings_override_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    cfg_file = paths.user_config_file()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(
        """
backend = "ollama"
max_steps = 50
default_profile = "coder"
""",
        encoding="utf-8",
    )

    s = load_settings()
    assert s.backend == "ollama"
    assert s.max_steps == 50
    assert s.default_profile == "coder"
    # Unspecified fields retain defaults
    assert s.mode == "ask"
    assert s.banner is True
    assert s.shell_timeout == 120

    assert default_profile_name() == "coder"


def test_save_setting_coercion_and_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    save_setting("banner", "false")
    save_setting("max_steps", "30")
    save_setting("mode", "yolo")
    save_setting("models_dir", str(tmp_path / "custom_models"))

    s = load_settings()
    assert s.banner is False
    assert s.max_steps == 30
    assert s.mode == "yolo"
    assert s.models_dir == str(tmp_path / "custom_models")

    # Unsetting models_dir by saving None
    save_setting("models_dir", None)
    s2 = load_settings()
    assert s2.models_dir is None


def test_save_setting_invalid_key_and_invalid_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    with pytest.raises(KeyError, match="Unknown setting"):
        save_setting("non_existent_key", "value")

    with pytest.raises(ValidationError):
        save_setting("mode", "unsupported_mode")

    with pytest.raises(ValidationError):
        save_setting("max_steps", "not_a_number")


def test_profile_merge_override_and_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    # Override package profile 'general'
    custom_general = ModelProfile(
        name="general",
        repo="CustomOrg/CustomGeneral-GGUF",
        file="custom_general.gguf",
        ctx=32768,
        min_vram_gb=8.0,
    )
    save_user_profile(custom_general)

    # Add new profile 'custom_agent'
    custom_agent = ModelProfile(
        name="custom_agent",
        repo="CustomOrg/CustomAgent-GGUF",
        file="agent.gguf",
        ollama="agent:latest",
    )
    save_user_profile(custom_agent)

    profiles = load_profiles()
    assert "custom_agent" in profiles
    assert profiles["custom_agent"].file == "agent.gguf"
    assert profiles["custom_agent"].ollama == "agent:latest"

    assert profiles["general"].repo == "CustomOrg/CustomGeneral-GGUF"
    assert profiles["general"].file == "custom_general.gguf"
    assert profiles["general"].ctx == 32768
    assert profiles["general"].min_vram_gb == 8.0

    # Ensure other package profiles are preserved
    assert "power" in profiles
    assert "coder" in profiles
    assert "lite" in profiles


def test_remove_user_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    # Removing from non-existent user models file
    assert remove_user_profile("nonexistent") is False

    custom_model = ModelProfile(name="temp_model", repo="foo/bar", file="temp.gguf")
    save_user_profile(custom_model)
    assert "temp_model" in load_profiles()

    assert remove_user_profile("temp_model") is True
    assert "temp_model" not in load_profiles()
    assert remove_user_profile("temp_model") is False

    # Overriding and removing a package profile reverts to package definition
    override_general = ModelProfile(name="general", repo="Override/General", file="gen.gguf")
    save_user_profile(override_general)
    assert load_profiles()["general"].repo == "Override/General"

    assert remove_user_profile("general") is True
    assert load_profiles()["general"].repo == "Qwen/Qwen3-8B-GGUF"


def test_resolve_model_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))
    s = Settings()

    # 1. p.path absolute
    abs_path = tmp_path / "models" / "absolute_model.gguf"
    p_abs = ModelProfile(name="test_abs", path=str(abs_path))
    assert resolve_model_path(p_abs, s) == abs_path

    # 2. p.path relative to root
    p_rel = ModelProfile(name="test_rel", path="custom_dir/rel_model.gguf")
    assert resolve_model_path(p_rel, s) == tmp_path / "custom_dir" / "rel_model.gguf"

    # 3. repo/file with default models_dir
    p_file = ModelProfile(name="test_file", repo="org/repo", file="model.gguf")
    assert resolve_model_path(p_file, s) == paths.default_models_dir() / "model.gguf"

    # 4. models_dir override in Settings
    custom_models_dir = tmp_path / "external_models"
    s_override = Settings(models_dir=str(custom_models_dir))
    assert models_dir(s_override) == custom_models_dir
    assert resolve_model_path(p_file, s_override) == custom_models_dir / "model.gguf"

    # 5. Missing both path and file raises ValueError
    p_none = ModelProfile(name="test_none")
    with pytest.raises(ValueError, match="neither 'path' nor 'file' configured"):
        resolve_model_path(p_none, s)


def test_corrupt_toml_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    # Corrupt config.toml
    cfg_file = paths.user_config_file()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text("invalid = [[ toml {{{", encoding="utf-8")

    with pytest.warns(UserWarning, match="Failed to load user config"):
        s = load_settings()
    assert s.backend == "llamacpp"
    assert s.default_profile == "general"

    # Corrupt models.toml
    m_file = paths.user_models_file()
    m_file.write_text("broken = [toml", encoding="utf-8")

    with pytest.warns(UserWarning, match="Failed to load user models"):
        profiles = load_profiles()
    assert "general" in profiles
    assert profiles["general"].repo == "Qwen/Qwen3-8B-GGUF"

    # Saving setting recovers from corrupt config.toml
    with pytest.warns(UserWarning, match="Existing user config .* was invalid"):
        save_setting("banner", "false")

    s_recovered = load_settings()
    assert s_recovered.banner is False


def test_lazy_directory_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    data_dir = tmp_path / "data"
    assert not data_dir.exists()

    save_setting("banner", True)
    assert data_dir.is_dir()
    assert (data_dir / "config.toml").is_file()

    save_user_profile(ModelProfile(name="custom", repo="org/m", file="m.gguf"))
    assert (data_dir / "models.toml").is_file()


def test_default_profile_name_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    # Initial default from package models.toml
    assert default_profile_name() == "general"

    # Override via user models.toml
    user_models = paths.user_models_file()
    user_models.parent.mkdir(parents=True, exist_ok=True)
    user_models.write_text('default = "power"\n', encoding="utf-8")
    assert default_profile_name() == "power"

    # Override via user config.toml (takes precedence over models.toml)
    user_cfg = paths.user_config_file()
    user_cfg.write_text('default_profile = "coder"\n', encoding="utf-8")
    assert default_profile_name() == "coder"
