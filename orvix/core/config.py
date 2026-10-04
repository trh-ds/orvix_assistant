"""Load config.toml into typed settings."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


class LLMConfig(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "qwen3.5:4b"
    keep_alive: int = -1
    num_ctx: int = 4096
    temperature: float = 0.6
    top_p: float = 0.95
    think: bool = False
    top_k_tools: int = 4


class RouterConfig(BaseModel):
    engine: str = "none"
    confidence_threshold: float = 0.6


class STTConfig(BaseModel):
    model: str = "base.en"
    compute_type: str = "int8"


class TTSConfig(BaseModel):
    engine: str = "piper"


class LoopConfig(BaseModel):
    max_tool_calls: int = 5
    tool_timeout_s: int = 30
    tool_output_cap: int = 2000
    confirm_timeout_s: int = 10


class PathsConfig(BaseModel):
    home: str = "~"
    db: str = "data/orvix.db"
    blocked: list[str] = Field(default_factory=list)

    @property
    def home_path(self) -> Path:
        return Path(self.home).expanduser()

    @property
    def db_path(self) -> Path:
        p = Path(self.db).expanduser()
        return p if p.is_absolute() else ROOT / p

    @property
    def blocked_paths(self) -> list[Path]:
        return [Path(b).expanduser() for b in self.blocked]


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.toml"
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        return Config.model_validate(tomllib.load(f))
