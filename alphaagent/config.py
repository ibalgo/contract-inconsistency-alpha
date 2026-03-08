from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_pem_from_env_file(env_file: str = ".env") -> str:
    """Extract a full PEM private key block from the raw .env file.

    python-dotenv cannot parse unquoted multi-line values, so we read the
    file directly and extract everything between BEGIN and END RSA markers.
    """
    try:
        content = Path(env_file).read_text()
    except FileNotFoundError:
        return ""

    # Match RSA PRIVATE KEY or PRIVATE KEY blocks
    match = re.search(
        r"(-----BEGIN (?:RSA )?PRIVATE KEY-----.*?-----END (?:RSA )?PRIVATE KEY-----)",
        content,
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kalshi_api_id: str
    kalshi_api_private_key: str = ""
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"

    polymarket_base_url: str = "https://gamma-api.polymarket.com"

    # Use ALPHAAGENT_DB_URL to avoid colliding with system DATABASE_URL env var
    database_url: str = Field(
        default="sqlite:///alphaagent.db",
        validation_alias="ALPHAAGENT_DB_URL",
    )

    cosine_similarity_threshold: float = 0.75
    min_shared_signals: int = 2
    embedding_model: str = "all-MiniLM-L6-v2"

    anthropic_api_key: str = ""

    @cached_property
    def kalshi_private_key(self):
        pem = self.kalshi_api_private_key.strip()

        # Replace literal \n with actual newlines (env var exported on one line)
        if "\\n" in pem:
            pem = pem.replace("\\n", "\n")

        # If dotenv only read the header line, fall back to reading the raw file
        if not pem or pem == "-----BEGIN RSA PRIVATE KEY-----":
            pem = _read_pem_from_env_file()

        if not pem:
            raise ValueError(
                "KALSHI_API_PRIVATE_KEY is missing or could not be parsed from .env. "
                "Wrap the value in double quotes or use KALSHI_API_PRIVATE_KEY_FILE."
            )

        return load_pem_private_key(pem.encode(), password=None)


settings = Settings()
