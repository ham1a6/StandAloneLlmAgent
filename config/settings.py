from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:7b"
    temperature: float = 0.2
    context_window: int = 32768


class LlamaCppConfig(BaseModel):
    model_path: str = "./models/model.gguf"
    n_gpu_layers: int = -1
    n_ctx: int = 32768
    temperature: float = 0.2


class AgentConfig(BaseModel):
    max_steps: int = 30
    context_strategy: str = "sliding"


class ShellToolConfig(BaseModel):
    enabled: bool = True
    timeout: int = 60
    allowed_commands: list[str] = []


class ToolsConfig(BaseModel):
    shell: ShellToolConfig = ShellToolConfig()


class PermissionsConfig(BaseModel):
    require_confirm_before_write: bool = True
    require_confirm_before_shell: bool = False


class Settings(BaseModel):
    backend: str = "ollama"
    ollama: OllamaConfig = OllamaConfig()
    llamacpp: LlamaCppConfig = LlamaCppConfig()
    agent: AgentConfig = AgentConfig()
    tools: ToolsConfig = ToolsConfig()
    permissions: PermissionsConfig = PermissionsConfig()


def load_settings(path: str = "settings.yaml") -> Settings:
    p = Path(path)
    if p.exists():
        with p.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return Settings.model_validate(data)
    return Settings()
