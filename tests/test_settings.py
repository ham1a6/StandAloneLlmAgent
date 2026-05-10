from pathlib import Path
from config.settings import load_settings, Settings


def test_defaults_when_no_file(tmp_path):
    settings = load_settings(str(tmp_path / "nonexistent.yaml"))
    assert isinstance(settings, Settings)
    assert settings.backend == "ollama"
    assert settings.ollama.model == "qwen2.5-coder:7b"
    assert settings.agent.max_steps == 30


def test_load_from_yaml(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "backend: ollama\n"
        "ollama:\n"
        "  model: llama3.1:8b\n"
        "  temperature: 0.5\n"
        "  context_window: 16384\n"
        "agent:\n"
        "  max_steps: 10\n",
        encoding="utf-8",
    )
    s = load_settings(str(tmp_path / "settings.yaml"))
    assert s.ollama.model == "llama3.1:8b"
    assert s.ollama.temperature == 0.5
    assert s.ollama.context_window == 16384
    assert s.agent.max_steps == 10


def test_partial_yaml_uses_defaults(tmp_path):
    (tmp_path / "s.yaml").write_text("backend: ollama\n", encoding="utf-8")
    s = load_settings(str(tmp_path / "s.yaml"))
    assert s.ollama.base_url == "http://localhost:11434"
    assert s.agent.max_steps == 30


def test_empty_yaml_uses_defaults(tmp_path):
    (tmp_path / "s.yaml").write_text("", encoding="utf-8")
    s = load_settings(str(tmp_path / "s.yaml"))
    assert s.backend == "ollama"


def test_permissions_defaults(tmp_path):
    s = load_settings(str(tmp_path / "none.yaml"))
    assert s.permissions.require_confirm_before_write is True
    assert s.permissions.require_confirm_before_shell is False
