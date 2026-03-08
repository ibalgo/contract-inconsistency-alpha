## Project Overview

This project builds an **agentic system that discovers alpha in prediction markets** by detecting logical, temporal, and structural inconsistencies between similar contracts across venues (e.g., Kalshi and Polymarket).

The system continuously ingests markets, parses their rules, compares constraints, and produces ranked **alpha flags** with explanations and suggested trading actions.

Primary outputs:

* Ranked inconsistency feed
* Counterexample scenarios where contracts resolve differently
* Alpha severity score and trade recommendation
* API endpoint for automated trading systems

---

## Data Source
API endpoint for getting markets information
* Kalshi API: https://api.elections.kalshi.com/trade-api/v2/markets
  * Requires `KALSHI_API_KEY` loaded from `.env`
* Polymarket API: https://gamma-api.polymarket.com/markets
  * Public API, no authentication required

Document
* Kalshi Doc: https://docs.kalshi.com/api-reference/market/get-markets
* Polymarket Doc: https://docs.polymarket.com/api-reference/markets/list-markets

## Environment

Secrets are loaded from a `.env` file at project root. Never hardcode credentials.

```
KALSHI_API_KEY=...
ANTHROPIC_API_KEY=...
```

---

## Core Principle

Prediction market contracts are **not interchangeable**, even when they appear identical.

Differences in:

* resolution source
* timezone cutoff
* reporting revisions
* event definitions
* threshold measurement
* settlement rules

can produce **divergent outcomes**.

The system’s job is to identify and quantify these divergences.

---

## Architecture Overview

Multi-agent pipeline:

Scout → Parser → Comparator → Counterexample → Alpha Rater → Brief

### 1. Scout Agent

Responsibility:
Discover candidate similar markets.

Inputs:

* Kalshi API
* Polymarket API

Outputs:

```
CandidatePair {
    market_a_id
    market_b_id
    similarity_score
    matching_basis
}
```

Matching methods:

* embedding similarity (rules + title)
* shared entities
* shared dates
* shared numeric thresholds

Matching strategy:

* Group markets by category within each venue first
* Only compare markets that share the same category — no cross-category comparisons
* Run embedding similarity and signal matching within each category bucket
* Normalize all prices to `float` in `[0.0, 1.0]` at ingest: Kalshi returns integer cents (e.g. `62` → `0.62`), Polymarket returns floats already in `[0, 1]`

Claude should prioritize **high recall**, not precision.

---

### 2. Parser Agent

Responsibility:
Convert unstructured rules text into structured constraints.

Output schema:

```
ContractConstraints {
    event_type
    entity
    threshold_value
    threshold_unit
    comparison_operator

    start_time
    end_time
    timezone

    resolution_source
    fallback_sources

    revision_policy

    occurrence_definition
    announcement_definition

    cancellation_conditions

    ladder_group_id
    complement_group_id
}
```

Rules:

* Extract explicitly stated constraints only
* Do not infer missing information
* Preserve original text references
* Mark unknown fields as null

Example output:

```
{
 threshold_value: 1000,
 threshold_unit: "cases",
 comparison_operator: ">=",
 end_time: "2026-12-31T23:59",
 timezone: "America/New_York",
 resolution_source: "CDC",
 revision_policy: "final revision only"
}
```

---

### 3. Comparator Agent

Responsibility:
Detect material differences.

Null field rule:

* Only compare fields that are non-null on **both** sides
* If a field is null on either side, skip it silently — absence of stated information is not an inconsistency

Comparison categories:

Time inconsistencies:

* timezone mismatch
* cutoff mismatch
* start/end window mismatch

Source inconsistencies:

* different resolution authority
* fallback differences
* revision policy differences

Definition inconsistencies:

* announced vs occurred
* measured vs reported
* estimated vs final

Structural inconsistencies:

* YES + NO ≠ 1
* ladder contracts not monotonic
* partitions do not sum to 1

Output:

```
Inconsistency {
    type
    severity
    description
    fields_involved
}
```

Severity levels:

CRITICAL
HIGH
MEDIUM
LOW

---

### 4. Counterexample Agent

Responsibility:
Generate concrete scenario where contracts resolve differently.

Uses LLM (Claude). Input: inconsistency type + both ContractConstraints objects + market titles.

Example:

```
Scenario:
Event occurs at 11:30 PM ET Dec 31

Kalshi cutoff: ET midnight
Polymarket cutoff: UTC midnight

Result:
Kalshi: YES
Polymarket: NO
```

This makes alpha actionable.

Claude must:

* use realistic timelines
* reference actual constraint differences from the provided constraints — do not invent values
* avoid impossible scenarios
* return null if no realistic divergence scenario is possible

---

### 5. Alpha Rater Agent

Responsibility:
Estimate trade value.

Inputs:

* inconsistency severity
* current prices
* liquidity
* structural divergence risk

Output:

```
AlphaScore {
    score: 0–100
    confidence: 0–1
    opportunity_type:
        arbitrage
        asymmetric
        avoid
        hedge
}
```

Heuristic priority:

CRITICAL structural violations
timezone cutoff mismatches
resolution source mismatches
ladder pricing violations

---

### 6. Brief Agent

Responsibility:
Produce human-readable explanation.

Uses LLM (Claude). Input: market titles, most severe Inconsistency, Counterexample, AlphaScore.

Claude must:

* not invent contract details not present in the inputs
* ground the trade idea in the actual alpha score and counterexample
* keep each section to 1–3 sentences

Output format:

```
SUMMARY
Markets appear similar but resolve differently.

KEY DIFFERENCE
Kalshi uses ET cutoff, Polymarket uses UTC.

WHY IT MATTERS
Events near cutoff can resolve differently.

TRADE IDEA
Buy YES on one venue and NO on the other if spread exceeds X.
```

Must be concise and actionable.

---

## API Specification

GET /alpha_flags

Returns:

```
[
  {
    market_a
    market_b
    alpha_score
    severity
    inconsistency_type
    recommendation
  }
]
```

GET /is_safe_pair?market_a=&market_b=

Returns:

```
{
 safe: true/false,
 reasons: []
}
```

---

## Data Model

Database: **SQLite** for MVP (file: `alphaagent.db`).
ORM: SQLAlchemy — migrating to Postgres later requires only changing the connection string.

Tables:

markets
constraints
candidate_pairs
inconsistencies
alpha_flags

Each constraint must be stored separately for auditing.

The pipeline runs on a schedule in the background and writes results into the DB.
The API only reads from the DB — it never triggers the pipeline directly.

---

## Coding Standards

Language:

Python 3.11+

Required libraries:

pydantic
fastapi
httpx
numpy
sqlalchemy
sentence-transformers
anthropic
python-dotenv

---

## LLM Usage Rules

LLM (Claude) is used in exactly three steps: Parser, Counterexample, and Brief.

Parser:

* Always output structured JSON — no prose outside the JSON object
* Never hallucinate contract rules
* Quote original rule text when referencing constraints
* Mark unknown fields explicitly null
* Prefer correctness over completeness

Counterexample:

* Ground scenario strictly in the constraint values provided as input
* Do not invent thresholds, dates, or sources not present in the input
* Return null if no realistic divergence scenario is possible

Brief:

* Do not invent contract details not present in the inputs
* Ground the trade idea in the actual alpha score and counterexample values
* Output the four sections (SUMMARY, KEY DIFFERENCE, WHY IT MATTERS, TRADE IDEA) in plain text

---

## Severity Classification Rules

CRITICAL

Logical impossibility
Complement violation
Partition violation

HIGH

Timezone mismatch
Resolution source mismatch

MEDIUM

Revision policy mismatch
Definition ambiguity

LOW

Minor wording differences

---

## Alpha Prioritization Rules

Prioritize:

cross-venue inconsistencies
contracts with liquidity
contracts near resolution

Deprioritize:

low volume markets
far future contracts

---

## Non-Goals

Do not:

Execute trades automatically
Invent contract rules
Predict event outcomes

Focus strictly on **contract structure and logic**.

---

## Testing Requirements

Parser must pass cases:

timezone extraction
threshold extraction
source extraction

Comparator must detect:

cutoff mismatches
ladder inconsistencies

Counterexample must produce valid divergence scenario.

---

## MVP Scope

Required:

Kalshi ingestion
Polymarket ingestion
rules parsing
inconsistency detection

Optional:

dashboard
alerts

---

## Long Term Extensions

automated arbitrage execution
multi-venue support
probability normalization
portfolio risk integration

---

## Guiding Philosophy

Correct contract interpretation is alpha.

Small rule differences produce real profit opportunities.

Precision and explainability are more important than speed.

