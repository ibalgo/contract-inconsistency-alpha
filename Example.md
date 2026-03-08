# Market Data Ingestion: Kalshi & Polymarket

A reference guide for correctly fetching, authenticating, and normalizing market data from both venues.

---

## Kalshi

### Authentication

Kalshi uses **RSA-PSS signed request headers** — not a simple API key token. Every request must be signed fresh.

**Required headers:**

| Header | Value |
|---|---|
| `KALSHI-ACCESS-KEY` | Your API key ID (UUID) |
| `KALSHI-ACCESS-TIMESTAMP` | Current Unix time in **milliseconds** |
| `KALSHI-ACCESS-SIGNATURE` | Base64-encoded RSA-PSS signature |

**Signature message format:**
```
{timestamp_ms}{METHOD_UPPERCASE}{path}
```
Example: `1709900000000GET/trade-api/v2/markets`

**Important notes:**
- The path must match exactly what is sent in the request (no query string).
- Use `SHA-256` as both the hash and the MGF1 algorithm.
- Salt length must be `PSS.DIGEST_LENGTH` (32 bytes for SHA-256).
- Timestamp must be milliseconds, not seconds.

```python
import base64
import time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key

def build_kalshi_auth_headers(method: str, path: str, private_key) -> dict:
    """Generate fresh RSA-PSS signed headers for one Kalshi API request."""
    ts_ms = str(int(time.time() * 1000))
    message = f"{ts_ms}{method.upper()}{path}".encode()

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": "your-api-key-id",
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }

# Load key from PEM
with open("kalshi_private.pem", "rb") as f:
    private_key = load_pem_private_key(f.read(), password=None)
```

### PEM Key in .env — Common Pitfall

`python-dotenv` cannot parse unquoted multi-line PEM blocks — it reads only the first line. Work around this by reading the `.env` file directly with a regex:

```python
import re
from pathlib import Path

def read_pem_from_env_file(env_file: str = ".env") -> str:
    content = Path(env_file).read_text()
    match = re.search(
        r"(-----BEGIN (?:RSA )?PRIVATE KEY-----.*?-----END (?:RSA )?PRIVATE KEY-----)",
        content,
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""
```

Alternatively, store the key on one line with literal `\n` characters and replace them at load time:

```python
pem = pem.replace("\\n", "\n")
```

### Fetching Markets

- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
- **Endpoint:** `GET /markets`
- **Pagination:** cursor-based — pass `cursor` from the previous response until it is empty or the batch is empty.
- **Page size:** max `200` per request.

```python
import httpx

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
PATH = "/trade-api/v2/markets"

async def fetch_kalshi_markets(private_key, api_key_id: str) -> list[dict]:
    markets = []
    cursor = ""

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        while True:
            params = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor

            # Sign using the full path (no query string)
            headers = build_kalshi_auth_headers("GET", PATH)
            headers["KALSHI-ACCESS-KEY"] = api_key_id

            response = await client.get("/markets", params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

            batch = data.get("markets", [])
            markets.extend(batch)

            cursor = data.get("cursor", "")
            if not batch or not cursor:
                break

    return markets
```

### Response Fields

Key fields returned per market:

| Field | Type | Notes |
|---|---|---|
| `ticker` | string | Unique market ID, e.g. `"BTCUSD-25DEC-B90000"` |
| `event_ticker` | string | Parent event, e.g. `"BTCUSD-25DEC"` |
| `yes_sub_title` | string | Human-readable title |
| `rules_primary` | string | Main resolution rules |
| `rules_secondary` | string | Additional rules |
| `yes_bid_dollars` | string | Best YES bid as dollar string, e.g. `"0.62"` |
| `yes_ask_dollars` | string | Best YES ask as dollar string |
| `no_bid_dollars` | string | Best NO bid |
| `no_ask_dollars` | string | Best NO ask |
| `last_price_dollars` | string | Last traded price as dollar string |
| `volume` | number | Total contract volume |
| `close_time` | string | ISO 8601 close datetime |

### Price Normalization

Kalshi returns prices as dollar strings in `[0, 1]` (e.g. `"0.62"`, not `62`). Average bid and ask for a midpoint:

```python
def midpoint(bid: str | None, ask: str | None) -> float | None:
    try:
        b = float(bid) if bid not in (None, "", "0") else None
        a = float(ask) if ask not in (None, "", "0") else None
        if b is not None and a is not None:
            return (b + a) / 2.0
        return b or a
    except (TypeError, ValueError):
        return None

def normalize_kalshi_market(raw: dict) -> dict:
    ticker = raw.get("ticker", "")
    event_ticker = raw.get("event_ticker", "")
    # First segment of event_ticker is the category code
    category_raw = event_ticker.split("-")[0] if event_ticker else None

    title = raw.get("yes_sub_title") or raw.get("title") or ticker
    rules_text = " ".join(filter(None, [
        raw.get("rules_primary", ""),
        raw.get("rules_secondary", ""),
    ])).strip() or None

    yes_price = midpoint(raw.get("yes_bid_dollars"), raw.get("yes_ask_dollars"))
    if yes_price is None:
        lp = raw.get("last_price_dollars")
        yes_price = float(lp) if lp else None

    no_price = midpoint(raw.get("no_bid_dollars"), raw.get("no_ask_dollars"))
    if no_price is None and yes_price is not None:
        no_price = 1.0 - yes_price

    return {
        "venue": "kalshi",
        "venue_id": ticker,
        "category": category_raw,
        "title": title,
        "rules_text": rules_text,
        "close_time": raw.get("close_time"),
        "yes_price": yes_price,   # float in [0.0, 1.0]
        "no_price": no_price,     # float in [0.0, 1.0]
        "volume": raw.get("volume"),
    }
```

---

## Polymarket

### Authentication

Polymarket's Gamma API is **public — no authentication required**.

### Fetching Markets

- **Base URL:** `https://gamma-api.polymarket.com`
- **Endpoint:** `GET /markets`
- **Pagination:** offset-based — increment `offset` by `limit` until a batch smaller than `limit` is returned.
- **Page size:** `100` recommended.

```python
import httpx

BASE_URL = "https://gamma-api.polymarket.com"

async def fetch_polymarket_markets() -> list[dict]:
    markets = []
    offset = 0
    limit = 100

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        while True:
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset,
            }
            response = await client.get("/markets", params=params)
            response.raise_for_status()
            batch = response.json()

            # Response may be a list or {"markets": [...]}
            if not isinstance(batch, list):
                batch = batch.get("markets", [])

            markets.extend(batch)

            if len(batch) < limit:
                break
            offset += limit

    return markets
```

### Response Fields

Key fields returned per market:

| Field | Type | Notes |
|---|---|---|
| `conditionId` | string | Unique market ID |
| `question` | string | Market title / question |
| `description` | string | Full resolution rules |
| `category` | string | Category tag (may be missing) |
| `outcomePrices` | string | JSON-encoded price array, e.g. `'["0.62", "0.38"]'` |
| `bestAsk` | string | Best ask price (fallback) |
| `bestBid` | string | Best bid price (fallback) |
| `volume` | number | Total volume |
| `volumeNum` | number | Alternate volume field |
| `endDate` | string | ISO 8601 end datetime |

### Price Normalization — Critical Pitfall

`outcomePrices` is a **JSON-encoded string**, not a list. You must call `json.loads()` on it before indexing. Prices are already floats in `[0, 1]`.

```python
import json

def normalize_polymarket_market(raw: dict) -> dict:
    title = raw.get("question") or raw.get("title") or ""
    venue_id = raw.get("conditionId") or raw.get("id") or ""

    yes_price = None
    no_price = None

    # outcomePrices is a JSON-encoded string: '["0.62", "0.38"]'
    outcome_prices_raw = raw.get("outcomePrices")
    if outcome_prices_raw:
        try:
            prices = json.loads(outcome_prices_raw)  # Must call json.loads!
            yes_price = float(prices[0]) if len(prices) > 0 else None
            no_price  = float(prices[1]) if len(prices) > 1 else None
        except (json.JSONDecodeError, IndexError, TypeError, ValueError):
            pass

    # Fallback if outcomePrices is missing
    if yes_price is None:
        try:
            yes_price = float(raw["bestAsk"]) if raw.get("bestAsk") else None
        except (TypeError, ValueError):
            pass
    if no_price is None:
        try:
            no_price = float(raw["bestBid"]) if raw.get("bestBid") else None
        except (TypeError, ValueError):
            pass

    volume = None
    try:
        v = raw.get("volume") or raw.get("volumeNum")
        volume = float(v) if v is not None else None
    except (TypeError, ValueError):
        pass

    return {
        "venue": "polymarket",
        "venue_id": venue_id,
        "category": raw.get("category"),
        "title": title,
        "rules_text": raw.get("description"),
        "close_time": raw.get("endDate") or raw.get("end_date_iso"),
        "yes_price": yes_price,   # float in [0.0, 1.0]
        "no_price": no_price,     # float in [0.0, 1.0]
        "volume": volume,
    }
```

---

## Fetching Both Concurrently

```python
import asyncio

async def fetch_all_markets(private_key, api_key_id: str):
    kalshi_raw, polymarket_raw = await asyncio.gather(
        fetch_kalshi_markets(private_key, api_key_id),
        fetch_polymarket_markets(),
    )

    kalshi_normalized   = [normalize_kalshi_market(m)     for m in kalshi_raw]
    polymarket_normalized = [normalize_polymarket_market(m) for m in polymarket_raw]

    print(f"Kalshi: {len(kalshi_normalized)} markets")
    print(f"Polymarket: {len(polymarket_normalized)} markets")

    return kalshi_normalized, polymarket_normalized
```

---

## Common Mistakes

| Mistake | Effect | Fix |
|---|---|---|
| Signing with seconds instead of milliseconds | 401 Unauthorized | Use `int(time.time() * 1000)` |
| Including query string in signed path | 401 Unauthorized | Sign only the path, e.g. `/trade-api/v2/markets` |
| Reading PEM key with python-dotenv | Key truncated to first line | Use regex on raw `.env` file or store key on one line with `\n` |
| Treating `outcomePrices` as a list | `TypeError` on index | Call `json.loads()` first |
| Treating Kalshi prices as integers | Prices 62x too large | Dollar strings are already in `[0,1]` — just `float()` them |
| Stopping Polymarket pagination on empty dict | Misses last page | Check `len(batch) < limit`, not truthiness of response |

---

## Environment Setup

`.env` file:

```
KALSHI_API_ID=your-uuid-key-id
KALSHI_API_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----
ANTHROPIC_API_KEY=sk-ant-...
```

Required packages:

```
httpx
cryptography
python-dotenv
pydantic-settings
```
