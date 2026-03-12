from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from market_ingestion.config import settings


def _build_kalshi_auth_headers(method: str, path: str) -> dict[str, str]:
    """Generate fresh RSA-PSS signed headers for a Kalshi API request."""
    ts_ms = str(int(time.time() * 1000))
    message = f"{ts_ms}{method.upper()}{path}".encode()

    signature = settings.kalshi_private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(signature).decode()

    return {
        "KALSHI-ACCESS-KEY": settings.kalshi_api_id,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
    }
