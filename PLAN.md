# AlphaAgent — Implementation Plan

## Overview

The project is divided into four phases. Each phase produces working, testable code before the next begins. Phases 1–2 are prerequisites for everything else. Phases 3–4 can be partially parallelized once the data layer is in place.

```
Phase 1: Foundation       → DB schema, models, config, project structure
Phase 2: Ingestion        → Fetch and store markets from both venues (Scout)
Phase 3: Intelligence     → Parse, compare, generate counterexamples
Phase 4: Scoring & API    → Alpha Rater, Brief, FastAPI endpoints
```

---

## Phase 1: Foundation

**Goal:** Set up the project skeleton. No business logic yet — just infrastructure every other module depends on.

### Tasks

**1.1 Project structure**
```
alphaagent/
  agents/
    scout.py
    parser.py
    comparator.py
    counterexample.py
    rater.py
    brief.py
  db/
    models.py
    session.py
  api/
    routes.py
  config.py
  main.py
.env
requirements.txt
```

**1.2 Configuration**
- Load `.env` with `python-dotenv`
- Expose `KALSHI_API_KEY` and `ANTHROPIC_API_KEY` through a `config.py` module
- Raise at startup if required keys are missing

**1.3 Database models**
Define SQLAlchemy ORM models for all five tables:

| Model | Key fields |
|---|---|
| `Market` | `id`, `venue`, `category`, `title`, `rules_text`, `close_time`, `yes_price`, `no_price`, `volume` |
| `Constraint` | `market_id` (FK), all `ContractConstraints` fields as columns |
| `CandidatePair` | `market_a_id`, `market_b_id`, `similarity_score`, `matching_basis` (JSON) |
| `Inconsistency` | `pair_id` (FK), `type`, `severity`, `description`, `fields_involved` (JSON) |
| `AlphaFlag` | `pair_id` (FK), `score`, `confidence`, `opportunity_type`, `brief_text` |

**1.4 Pydantic schemas**
Define Pydantic models mirroring the DB models for validation and serialization:
- `MarketIn`, `ContractConstraints`, `CandidatePair`, `Inconsistency`, `AlphaScore`

**1.5 Database**
- Use **SQLite** for MVP — no server required, single file on disk
- Access via SQLAlchemy ORM so migrating to Postgres later is a one-line config change:
  - SQLite: `sqlite:///alphaagent.db`
  - Postgres: `postgresql://user:pass@host/dbname`
- The pipeline runs on a schedule in the background and writes results into the DB
- The API only reads from the DB — never triggers the pipeline directly

**1.6 Dependencies**
Write `requirements.txt`:
```
fastapi
uvicorn
httpx
pydantic
sqlalchemy
sentence-transformers
anthropic
python-dotenv
numpy
```

### Deliverable
Running `python main.py` starts the app with an empty DB and no errors. All tables created.

---

## Phase 2: Ingestion (Scout)

**Goal:** Fetch all active markets from Kalshi and Polymarket, normalize prices, and identify candidate pairs.

### Tasks

**2.1 Kalshi client** (`agents/scout.py`)
- Authenticated `httpx` client using `KALSHI_API_KEY` in headers
- Paginate through all active markets
- Map raw API response fields to `Market` model
- Normalize price: `yes_price = raw_yes_bid / 100`

**2.2 Polymarket client** (`agents/scout.py`)
- Unauthenticated `httpx` client
- Paginate through all active markets
- Map raw API response fields to `Market` model
- Price is already in `[0.0, 1.0]`, store as-is

**2.3 Category bucketing**
- Extract `category` from each venue's API response
- Group markets by category before any comparison
- Only pair Kalshi × Polymarket markets that share the same category

**2.4 Embedding computation**
- Load `sentence-transformers` model once at startup (e.g. `all-MiniLM-L6-v2`)
- Encode `title + " " + rules_text` for each market
- Store embeddings in memory (not DB) during a pipeline run

**2.5 Signal extraction**
- Extract dates using regex (`YYYY-MM-DD`, written months, etc.)
- Extract numeric thresholds (integers and decimals with optional units)
- Extract named entities using a lightweight NLP library (e.g. `spacy` with `en_core_web_sm`)

**2.6 Pair scoring and emission**
- Compute cosine similarity for every cross-venue pair within each category
- Flag pair if cosine similarity > threshold (start with `0.75`, tune later)
- Flag pair if it shares ≥ 2 structured signals
- Write `CandidatePair` rows to DB

### Deliverable
Running the Scout produces populated `markets` and `candidate_pairs` tables. Inspect results manually to validate pair quality.

---

## Phase 3: Intelligence

**Goal:** For each candidate pair, parse constraints, detect inconsistencies, and generate counterexamples. This is the core of the system.

### Tasks — can be worked on in parallel once Phase 2 is done

---

### 3A: Parser (`agents/parser.py`)

**3A.1 Prompt design**
- Write a system prompt that instructs Claude to extract only explicitly stated facts
- Include the full `ContractConstraints` schema in the prompt
- Instruct it to output only a JSON object, with `null` for unknown fields
- Instruct it to include a `source_quote` for each non-null field

**3A.2 Claude API call**
- Use `anthropic` client with structured output
- Parse and validate the response with the `ContractConstraints` Pydantic model
- On JSON parse failure: log the raw response and store a failed parse record

**3A.3 Storage**
- Write one `Constraint` row per market after parsing
- Skip re-parsing if a valid constraint already exists for a market

**3A.4 Tests**
- Unit test with 3–5 hardcoded rules text samples
- Assert correct extraction of: timezone, threshold, resolution source, revision policy
- Assert that absent fields are `null`, not guessed

---

### 3B: Comparator (`agents/comparator.py`)

**3B.1 Field comparison logic**
- For each pair in `candidate_pairs`, load both `Constraint` rows
- Iterate over all comparable fields
- Skip any field where either side is `null`
- For time fields: normalize both to UTC before comparing

**3B.2 Inconsistency classification**
- Implement the full severity table from PROJECT.md as a decision function
- Structural checks (complement, partition, ladder) operate on prices from the `Market` row, not constraints
- Emit one `Inconsistency` row per detected difference

**3B.3 Tests**
- Unit test each inconsistency type with crafted constraint pairs
- Assert correct severity assignment
- Assert null fields are silently skipped

---

### 3C: Counterexample (`agents/counterexample.py`)

**3C.1 Prompt design**
- Pass: inconsistency type, both `ContractConstraints` objects, both market titles
- Instruct Claude to ground the scenario strictly in the provided values
- Instruct it to return `null` if no realistic scenario is possible
- Output: structured JSON with `scenario`, `market_a_outcome`, `market_b_outcome`, `basis`

**3C.2 Claude API call**
- One call per `Inconsistency` record
- Validate response as JSON; store `null` on failure

**3C.3 Storage**
- Store counterexample text on the `Inconsistency` row (add `counterexample` JSON column)

### Deliverable for Phase 3
Given a candidate pair, the system produces: parsed constraints, a list of inconsistencies with severities, and a counterexample scenario for each inconsistency.

---

## Phase 4: Scoring & API

**Goal:** Score each opportunity, generate the brief, and expose results via API.

### Tasks

**4.1 Alpha Rater** (`agents/rater.py`)
- Implement the deterministic scoring function from PROJECT.md
- Inputs: `Inconsistency`, prices from `Market`, volume, `Counterexample`
- Base score by severity + bonuses + cap at 100
- Classify opportunity type
- Write `AlphaFlag` row

**4.2 Brief** (`agents/brief.py`)
- Prompt Claude with: market titles, most severe `Inconsistency`, `Counterexample`, `AlphaScore`
- Instruct it to output the four-section plain text format
- Store result in `AlphaFlag.brief_text`

**4.3 Pipeline runner** (`main.py`)
- Orchestrate the full sequence: Scout → Parser → Comparator → Counterexample → Rater → Brief
- Run on demand or on a schedule
- Log progress and errors at each step

**4.4 API endpoints** (`api/routes.py`)
- `GET /alpha_flags` — query `AlphaFlag` table, join with `Market` and `Inconsistency`, return ranked by score descending
- `GET /is_safe_pair?market_a=&market_b=` — look up the pair, return `{ safe: bool, reasons: [] }` based on whether any HIGH/CRITICAL inconsistencies exist

**4.5 End-to-end test**
- Run the full pipeline against live APIs
- Verify at least one `AlphaFlag` is produced with a non-null brief

### Deliverable
`GET /alpha_flags` returns a ranked list of real opportunities. The system is usable end-to-end.

---

## Dependency Graph

```
Phase 1 (Foundation)
    └── Phase 2 (Ingestion / Scout)
            ├── Phase 3A (Parser)     ─┐
            ├── Phase 3B (Comparator)  ├── Phase 4 (Scoring & API)
            └── Phase 3C (Counterex.) ─┘
```

Phase 3A, 3B, 3C all depend on Phase 2 being complete but are independent of each other and can be built in parallel.

---

## Work Division (2 developers)

### Developer A — Data & Matching
Owns everything deterministic: ingestion, embedding, matching, comparison, scoring.

| Phase | Work |
|---|---|
| Phase 1 | DB models, config, project structure, Pydantic schemas |
| Phase 2 | Kalshi client, Polymarket client, category bucketing, embedding, signal extraction, pair scoring |
| Phase 3B | Comparator — field comparison, severity classification |
| Phase 4.1 | Alpha Rater |
| Phase 4.3 | Pipeline runner |
| Phase 4.4 | API endpoints |

### Developer B — LLM & Intelligence
Owns all LLM-touching components: prompt design, API calls, output validation.

| Phase | Work |
|---|---|
| Phase 1 | `requirements.txt`, shared Pydantic schemas (can collaborate) |
| Phase 3A | Parser — prompt design, Claude API call, validation, tests |
| Phase 3C | Counterexample — prompt design, Claude API call, storage |
| Phase 4.2 | Brief — prompt design, Claude API call, storage |
| Phase 4.5 | End-to-end test |

---

## Risk Areas

| Risk | Mitigation |
|---|---|
| Kalshi or Polymarket API schema changes | Isolate API mapping in thin client functions; fail loudly on unexpected fields |
| LLM returns invalid JSON | Always validate with Pydantic; log raw response; store parse failure, do not crash pipeline |
| Category field names differ between venues | Build an explicit category mapping table before running pair matching |
| Embedding model cold start is slow | Load model once at startup, not per request |
| Too many candidate pairs overwhelming downstream LLM steps | Tune cosine similarity threshold upward if pair volume is too high |
