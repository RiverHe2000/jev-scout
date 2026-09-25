"""Server-only configuration. Secrets are never serialized to the client."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    typesafe_key: str = ""
    openrouter_key: str = ""
    jev_model: str = "jev-latest"
    llm_base_url: str = ""
    llm_key: str = ""
    llm_model: str = "qwen3-4b"
    input_price: float | None = None
    llm_input_price: float | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    autoseed: bool = True
    worker_enabled: bool = True
    model_timeout: float = 90.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "scout.sqlite3"

    @property
    def jev_provider(self) -> str | None:
        return "typesafe" if self.typesafe_key else "openrouter" if self.openrouter_key else None

    @property
    def jev_endpoint(self) -> str:
        if self.jev_provider == "openrouter":
            return "https://openrouter.ai/api/alpha/decisions"
        return "https://api.typesafe.ai/v1/systemone"

    @property
    def resolved_jev_model(self) -> str:
        if self.jev_provider == "openrouter" and not self.jev_model.startswith(("typesafe/", "~typesafe/")):
            return "typesafe/jev-1.13" if self.jev_model == "jev-latest" else f"typesafe/{self.jev_model}"
        return self.jev_model

    @property
    def available_modes(self) -> list[str]:
        return ["baseline"] + (["jev"] if self.jev_provider else []) + (["llm"] if self.llm_base_url else [])

    def public(self) -> dict:
        provider = urlparse(self.llm_base_url).hostname or ""
        return {
            "jev_configured": self.jev_provider is not None,
            "jev_provider": self.jev_provider,
            "model": self.resolved_jev_model,
            "llm_configured": bool(self.llm_base_url),
            "llm_model": self.llm_model,
            "llm_provider": "local" if provider in {"localhost", "127.0.0.1", "::1"} else provider,
            "available_modes": self.available_modes,
            "default_mode": "jev" if self.jev_provider else "llm" if self.llm_base_url else "baseline",
            "price_per_million_input": self.input_price,
            "local_only": True,
            "database_path_display": "runtime/scout.sqlite3",
            "version": "0.1.0",
        }

    @classmethod
    def load(cls) -> Settings:
        values = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}

        def value(key: str, default: str = "") -> str:
            return str(values.get(key) or default).strip()

        def price(key: str) -> float | None:
            raw = value(key)
            if not raw:
                return None
            result = float(raw)
            if not 0 <= result <= 10000:
                raise ValueError(f"Invalid {key}: expected a non-negative finite USD price.")
            return result

        data_dir = Path(value("JEV_SCOUT_DATA_DIR", "runtime"))
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        host = value("JEV_SCOUT_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "This single-user edition must bind to localhost. Use an authenticated proxy for remote access."
            )
        llm_base = value("JEV_SCOUT_LLM_BASE_URL").rstrip("/")
        if llm_base:
            try:
                parsed = urlparse(llm_base)
                _ = parsed.port
            except ValueError:
                raise ValueError("JEV_SCOUT_LLM_BASE_URL has an invalid hostname or port.") from None
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "JEV_SCOUT_LLM_BASE_URL must be an HTTP(S) URL without embedded credentials."
                )
            if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Remote model endpoints require HTTPS.")
        port = int(value("JEV_SCOUT_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError("JEV_SCOUT_PORT must be between 1 and 65535.")
        timeout = float(value("JEV_SCOUT_MODEL_TIMEOUT", "90"))
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 300:
            raise ValueError("JEV_SCOUT_MODEL_TIMEOUT must be between 0.1 and 300 seconds.")
        return cls(
            data_dir=data_dir.resolve(),
            typesafe_key=value("TYPESAFE_API_KEY"),
            openrouter_key=value("OPENROUTER_API_KEY"),
            jev_model=value("JEV_SCOUT_MODEL", "jev-latest"),
            llm_base_url=llm_base,
            llm_key=value("JEV_SCOUT_LLM_API_KEY"),
            llm_model=value("JEV_SCOUT_LLM_MODEL", "qwen3-4b"),
            input_price=price("JEV_SCOUT_PRICE_PER_MILLION_INPUT"),
            llm_input_price=price("JEV_SCOUT_LLM_PRICE_PER_MILLION_INPUT"),
            host=host,
            port=port,
            autoseed=value("JEV_SCOUT_AUTOSEED", "true").lower() == "true",
            worker_enabled=value("JEV_SCOUT_WORKER", "true").lower() == "true",
            model_timeout=timeout,
        )
