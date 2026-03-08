# AlphaAgent — Project Overview

## What It Does

AlphaAgent discovers trading alpha in prediction markets by detecting logical, temporal, and structural inconsistencies between similar contracts across venues (Kalshi and Polymarket).

Even when two contracts appear identical, differences in resolution source, timezone cutoffs, revision policies, or event definitions can cause them to resolve differently — creating exploitable price divergences.

## Pipeline

```
Scout → Parser → Comparator → Counterexample → Alpha Rater → Brief
```

## LLM Usage Summary

| Step | LLM | Purpose |
|---|---|---|
| Scout | No | Deterministic embedding + signal matching |
| Parser | Yes | Extract structured constraints from rules text |
| Comparator | No | Deterministic field-by-field comparison |
| Counterexample | Yes | Generate realistic divergence scenario |
| Alpha Rater | No | Deterministic scoring rules |
| Brief | Yes | Write human-readable summary and trade idea |

---

## Step 1: Scout

**Goal:** Pull all active markets from both venues and identify candidate pairs that appear to cover the same real-world event.

**Inputs:**
- Kalshi REST API: `https://api.elections.kalshi.com/trade-api/v2/markets`
  - Requires `KALSHI_API_KEY` loaded from `.env`
- Polymarket REST API: `https://gamma-api.polymarket.com/markets`
  - Public API, no authentication required

**What to do:**
1. Fetch all active markets from both APIs, paginating through all results.
2. For each market, store: `id`, `venue`, `category`, `title`, `rules_text`, `close_time`, `volume`, and normalized prices (see price normalization below).
3. **Price normalization:** Both venues express prices as a probability in `[0.0, 1.0]`. Kalshi returns integer cents (e.g. `62` → `0.62`). Polymarket returns floats in `[0, 1]`. Normalize all prices to `float` in `[0.0, 1.0]` at ingest time before storing.
4. Group markets by `category` within each venue. Only compare markets that share the same category — do not run cross-category comparisons.
5. Within each category, compute a text embedding for each market using `sentence-transformers` on `title + rules_text`.
6. For every cross-venue pair within the same category, compute cosine similarity between embeddings.
7. Additionally extract structured signals: dates mentioned, numeric thresholds, named entities. Use as secondary matching signals.
8. Emit a `CandidatePair` for every pair whose cosine similarity exceeds threshold OR that shares at least two structured signals (e.g. same date + same threshold).

**Output:**
```json
{
  "market_a_id": "kalshi:BTCUSD-25DEC",
  "market_b_id": "polymarket:0xabc123",
  "similarity_score": 0.91,
  "matching_basis": ["embedding", "shared_date:2025-12-25", "shared_threshold:100000"]
}
```

**Design note:** Prioritize high recall within each category. It is better to pass a non-matching pair downstream than to miss a true inconsistency here.

---

## Step 2: Parser

**Goal:** Convert the unstructured rules paragraph of each market into a structured `ContractConstraints` JSON object.

**Inputs:**
- Raw `rules_text` string for a single market.

**What to do:**
1. Send the rules text to Claude (Anthropic API) with a prompt instructing it to extract only explicitly stated facts.
2. The LLM must return a structured JSON conforming to the schema below.
3. Unknown or unstated fields must be set to `null` — never inferred or hallucinated.
4. The original text snippet that justifies each extracted field must be included as a `source_quote`.

**Output schema:**
```json
{
  "event_type": "price_threshold",
  "entity": "Bitcoin",
  "threshold_value": 100000,
  "threshold_unit": "USD",
  "comparison_operator": ">=",
  "start_time": null,
  "end_time": "2025-12-31T23:59:00",
  "timezone": "America/New_York",
  "resolution_source": "Coinbase",
  "fallback_sources": ["Kraken"],
  "revision_policy": "final value only",
  "occurrence_definition": null,
  "announcement_definition": null,
  "cancellation_conditions": "market cancelled if exchange halts trading",
  "ladder_group_id": null,
  "complement_group_id": null
}
```

**LLM usage rules:**
- Always output valid JSON. No prose outside the JSON object.
- Never invent rules. If the text is ambiguous, mark the field `null`.
- Quote the exact rule text that supports each non-null field.
- Prefer correctness over completeness.

---

## Step 3: Comparator

**Goal:** Given a `CandidatePair` and the two parsed `ContractConstraints`, detect every material difference between them.

**Inputs:**
- `ContractConstraints` for market A
- `ContractConstraints` for market B

**What to do:**
1. Compare each field side by side. **Only compare fields that are non-null on both sides.** If a field is null on either side, skip it silently — absence of stated information is not an inconsistency.
2. Classify each disagreement into a category and assign a severity:

| Category | Check | Severity |
|---|---|---|
| Timezone mismatch | `timezone` fields differ | HIGH |
| Cutoff mismatch | `end_time` differs after normalizing to UTC | HIGH |
| Window mismatch | `start_time` or `end_time` window differs | HIGH |
| Resolution source mismatch | `resolution_source` differs | HIGH |
| Fallback mismatch | `fallback_sources` differ | MEDIUM |
| Revision policy mismatch | `revision_policy` differs | MEDIUM |
| Definition mismatch | `occurrence_definition` vs `announcement_definition` conflict | MEDIUM |
| Complement violation | YES price + NO price ≠ 1.00 within tolerance | CRITICAL |
| Partition violation | Multiple legs of a ladder do not sum to 1.00 | CRITICAL |
| Ladder monotonicity violation | Higher threshold leg priced above lower threshold leg | CRITICAL |
| Minor wording | All other text differences | LOW |

3. Emit one `Inconsistency` record per detected difference.

**Output:**
```json
{
  "type": "timezone_mismatch",
  "severity": "HIGH",
  "description": "Market A uses America/New_York, market B uses UTC.",
  "fields_involved": ["timezone", "end_time"]
}
```

**Design note:** All comparisons are deterministic code — no LLM. Severity levels follow strict rules above; do not improvise.

---

## Step 4: Counterexample

**Goal:** For each inconsistency, construct a concrete, realistic scenario that causes the two contracts to resolve differently.

**Inputs:**
- The `Inconsistency` record
- The two `ContractConstraints` objects

**What to do:**
1. Send the inconsistency type, both constraint objects, and both market titles to Claude.
2. Instruct the LLM to produce a realistic scenario grounded strictly in the provided constraint values — not invented facts.
3. The scenario must specify: the event description, the exact timestamp or value involved, the outcome for market A, and the outcome for market B.
4. If the LLM determines no realistic divergence scenario is possible given the constraints, it should return `null`.

**LLM usage rules:**
- Ground the scenario in the actual constraint values provided. Do not invent thresholds, dates, or sources not present in the input.
- The scenario must be realistic (plausible given real-world market behavior).
- Output structured JSON only.

**Output:**
```json
{
  "scenario": "Event occurs at 23:30 ET on Dec 31.",
  "market_a_outcome": "YES — falls within ET midnight cutoff",
  "market_b_outcome": "NO — UTC midnight is 19:00 ET, already passed",
  "basis": "timezone_mismatch"
}
```

---

## Step 5: Alpha Rater

**Goal:** Score the trading opportunity represented by each inconsistency.

**Inputs:**
- `Inconsistency` severity and type
- Normalized YES/NO prices on both venues (in `[0.0, 1.0]`)
- Volume/liquidity data from the Scout fetch
- The `Counterexample` (if available)

**What to do:**
1. Start with a base score derived from severity: CRITICAL → 80, HIGH → 60, MEDIUM → 35, LOW → 10.
2. Apply bonuses:
   - Counterexample successfully constructed: +15
   - Both markets have non-zero volume: +10
   - Contract closes within 7 days: +10
   - Price spread between venues exceeds 0.05: +10
3. Classify the opportunity type:
   - `arbitrage` — structural violation allows risk-free profit
   - `asymmetric` — one side is mispriced given the inconsistency
   - `hedge` — use one contract to hedge risk on the other
   - `avoid` — inconsistency makes both contracts unreliable
4. Cap the final score at 100.

**Output:**
```json
{
  "score": 85,
  "confidence": 0.78,
  "opportunity_type": "arbitrage"
}
```

**Design note:** No LLM — deterministic scoring rules applied to structured data.

---

## Step 6: Brief

**Goal:** Produce a short, plain-English summary of the alpha opportunity for a human trader.

**Inputs:**
- Market A and B titles and venues
- The most severe `Inconsistency` record
- The `Counterexample` (if available)
- The `AlphaScore`

**What to do:**
1. Send all inputs to Claude with instructions to write a concise 4-section brief.
2. Each section must be 1–3 sentences. Trade idea must reference specific prices or spread conditions from the alpha score.

**LLM usage rules:**
- Do not invent contract details not present in the inputs.
- Ground the trade idea in the actual alpha score and counterexample.
- Output the four sections in plain text with section headers.

**Output:**
```
SUMMARY
Both markets ask whether Bitcoin exceeds $100k by Dec 31, but use different resolution sources.

KEY DIFFERENCE
Kalshi resolves on Coinbase final price. Polymarket resolves on Kraken, which has an additional 30-minute lag.

WHY IT MATTERS
If the price crosses $100k after 23:30 ET, Coinbase and Kraken may disagree on the final print.

TRADE IDEA
Buy YES on Kalshi and NO on Polymarket if combined cost is below $0.98 and price is within 2% of threshold.
```

---

## API Endpoints

- `GET /alpha_flags` — returns all pairs ranked by alpha score, with severity, inconsistency type, and trade recommendation
- `GET /is_safe_pair?market_a=&market_b=` — returns `{ safe: bool, reasons: [] }` for a specific pair

---

## Data Model

| Table | Contents |
|---|---|
| `markets` | Raw market data from both venues, with normalized prices |
| `constraints` | Parsed `ContractConstraints` per market |
| `candidate_pairs` | Scout output with similarity scores |
| `inconsistencies` | Comparator output, one row per detected difference |
| `alpha_flags` | Final scored and briefed opportunities |

---

## Environment

Secrets are loaded from a `.env` file at project root:

```
KALSHI_API_KEY=...
ANTHROPIC_API_KEY=...
```

Never hardcode credentials.

---

## Tech Stack

- Python 3.11+
- FastAPI, Pydantic, SQLAlchemy, httpx
- sentence-transformers (Scout embeddings)
- Anthropic Claude API (Parser, Counterexample, Brief)
- python-dotenv (credential loading)

---

## Guiding Philosophy

> Correct contract interpretation is alpha. Small rule differences produce real profit opportunities. Precision and explainability are more important than speed.

## Non-Goals

- No automatic trade execution
- No event outcome prediction
- No hallucinated contract rules
