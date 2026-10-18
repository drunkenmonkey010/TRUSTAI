# Meridian Vendor AI Intelligence Engine

Agentic OSINT · AI-usage detection · third-party cyber-risk · adaptive investigation · benchmark evaluation

A runnable Python/Streamlit application that investigates vendors using **permitted public
information**, determines what can be **substantiated** about their AI usage and data flows,
assesses third-party risk with a **transparent deterministic model**, adapts investigation depth to
uncertainty and business criticality, preserves **verifiable evidence**, and evaluates itself against
a **strictly isolated held-out benchmark**.

> It prioritises traceable evidence, honest uncertainty, adaptive investigation, defensible risk
> scoring and benchmark integrity over visual polish. It is a working investigation system, **not** a
> dashboard of hardcoded results.

**V2.1** adds a full assurance lifecycle on top of the investigation engine: claim-level AI
classification (keyword mentions never become confirmed use), gap-driven vendor questionnaires, a
remediation / risk-decision workflow, a control-maturity matrix with a NIST/ISO/OWASP framework
crosswalk, AI threat modeling + attack paths, contract/policy clause analysis, change detection with a
risk diff, supply-chain concentration analytics, and an evidence-quality regression lab. See
`PROJECT_DOCUMENTATION.md` §23a for the full write-up.

---

## 1. Purpose

Given a workbook of third-party vendors, the engine:

- imports and normalises vendor records (preserving originals);
- derives business criticality and chooses an investigation depth;
- runs a twelve-agent OSINT investigation across a seven-layer methodology;
- extracts claims, links each to a cited evidence excerpt, and verifies quality;
- classifies AI usage into fixed labels and maps provider / data-flow relationships;
- scores risk deterministically with separate inherent / residual / confidence / uncertainty axes;
- produces prioritised recommendations and an independent QA review;
- **freezes** an immutable, hashed snapshot of its findings; and
- only then, on **explicit unlock**, compares those frozen findings against the benchmark.

## 2. Architecture

```
app.py + pages/           Streamlit UI (17 analyst pages)
config/                   settings (env), structured logging (secret redaction)
database/                 SQLite connection + versioned migrations (20 tables)
imports/                  flexible workbook/CSV import, normalization, dedup
connectors/               common interface + Brave, public web, SEC EDGAR, Tavily,
                          OpenCorporates, infra stubs, registry (live/offline mode)
evidence/                 Pydantic schemas, evidence ledger, verification, provenance
agents/                   12 agents + shared context + deterministic signal analysis + LLM abstraction
orchestration/            workflow, run manager (+ snapshot freezing), adaptive controller, scheduler
risk/                     deterministic scoring, editable weights, explanations
benchmark/                access control (the ONLY gateway), PDF parser, evaluator, schemas
reports/ exports/         vendor + portfolio reports, multi-format export center
tests/                    pytest suite (unit + end-to-end + mandatory isolation tests)
samples/                  bundled sample workbook + clearly-labelled offline sample sources
data/                     SQLite db (gitignored) + data/benchmark_protected/OPTIV.pdf
```

### The twelve agents
1. **Vendor Intake & Identity** – normalise, resolve aliases/parent hints, record identity ambiguity.
2. **Business Criticality** – assess **12 deep-criticality dimensions** (business-function centrality,
   system-of-record dependency, failure blast radius, time criticality, workaround availability,
   recoverability, transaction integrity, data consequence, exit/substitutability, regulatory
   criticality, financial materiality, concentration risk) from the operational input only; each
   dimension scored 0–3 with a basis and known/partial/unknown status, aggregated to a tier.
3. **OSINT Strategy** – questions, hypotheses and a bounded, layered, rationale-tagged query plan.
4. **Public OSINT Collection** – execute queries (live) or use analyst/sample sources (offline).
5. **Evidence Extraction** – extract claims with exact excerpts; direct vs inferred.
6. **Evidence Verification** – quality scoring, circular/duplicate and contradiction detection.
7. **AI-Usage Classification** – deterministic label over verified evidence (LLM only advises).
8. **Provider & Data-Flow Analysis** – evidence-backed relationships; customer-data flow marked honestly.
9. **Adaptive Depth Controller** – drives the seven-layer loop; continue/stop/escalate decisions.
10. **Risk Assessment** – deterministic model; separate inherent/residual/confidence/uncertainty.
11. **Recommendations** – prioritised, role-assigned, closure-conditioned actions.
12. **Independent QA** – unsupported claims, misclassification, overconfidence, contamination checks.

### Seven-layer OSINT methodology
1 Identity/baseline · 2 AI-signal discovery · 3 Product/technical validation · 4 Provider/dependency
mapping · 5 Data-flow/processing · 6 Corroboration/contradiction · 7 Risk-oriented gap closure.
The **adaptive controller** chooses the next action from criticality, data sensitivity, evidence
quality, uncertainty, contradictions, expected information gain, diminishing returns and remaining
budget — **not** a fixed "do N searches" rule. Layer coverage, evidence sufficiency, deployment
certainty and remaining uncertainty are tracked **separately**.

## 3. Connector selection & configuration

Connectors are selected per question, not fired blindly. The registry reports a clear **LIVE** vs
**OFFLINE** mode. Credentials are read from the environment and **never logged or displayed**.

| Connector | Env var(s) | Status |
|-----------|-----------|--------|
| Brave Search (primary search) | `BRAVE_SEARCH_API_KEY` | working (needs key) |
| Public web retrieval | – | working (robots-aware, no key) |
| SEC EDGAR | `SEC_CONTACT_EMAIL`, `SEC_USER_AGENT` | working (fair-access UA; no key) |
| Tavily (alt search) | `TAVILY_API_KEY` | working (needs key) |
| OpenCorporates | `OPENCORPORATES_API_KEY` | working (needs key) |
| SecurityTrails / Censys / Shodan | respective keys | **integration stubs** (never fabricate data) |
| LLM (OpenAI-compatible) | `LLM_PROVIDER=openai`, `OPENAI_API_KEY` | optional (advisory only) |

See `.env.example`. Copy it to `.env` and fill in only what you use.

### Offline / demo vs live OSINT
- **No search key → OFFLINE/DEMO.** The app still runs. For the fictional example vendor `V-000`
  it uses **clearly-labelled SAMPLE sources** (never presented as live OSINT). Real vendors
  investigated offline correctly yield **"Insufficient evidence"** unless you paste real source
  URLs/text on the Vendor Inventory page.
- **Search key present → LIVE.** Real queries and page retrievals are performed and cited.
- The engine **never** silently substitutes simulated results for live investigation.

## 4. Evidence model
`observation → extracted claim → inference → risk judgment → recommendation` are distinct types.
Every material claim references ≥1 evidence record (URL, canonical URL, excerpt, content hash,
publication **and** retrieval dates, authority, directness, freshness, independence, verification
status). Claims without evidence are flagged **unsupported** and sent to QA. URLs, excerpts and dates
are never invented.

## 5. Risk scoring
Deterministic and explainable (`risk/`). Dimensions are weighted (weights **editable** in the UI and
stored with each run, model version `risk-model-1.0.0`). Unknown fields are handled by a **documented
policy** — never silently zero, never treated as proof of failure. An LLM may *propose* a label, but
the numeric score is always computed from validated structured inputs.

## 6. Benchmark isolation (enforced by architecture + tests)
`OPTIV.pdf` is a **held-out answer key**, not an investigation source. All access flows through the
single gateway `benchmark/access_control.py`; the benchmark path lives only there and agents/connectors
**never import the benchmark package** (enforced by a static AST test). The benchmark is:
- **LOCKED** by default and inaccessible to automated investigation;
- unlockable **only after** a valid frozen snapshot exists, and only by **explicit** user action;
- compared read-only — evaluation never mutates the snapshot (hash verified before/after);
- fully **audited** (every unlock/access/evaluation is in an append-only log).

A frozen snapshot records *what the system found*, **not** that it is correct. The evaluation
independently surfaces missed findings, false positives and overconfidence.

---

## 6a. Investigation depth

Depth is driven by criticality. Choose **`auto`** (default) and the engine maps each vendor's derived
tier to a profile automatically — **Critical/High → deep, Medium → enhanced, Low → baseline** — so you
don't pick depth manually. The explicit profiles (`baseline`/`enhanced`/`deep`) remain as overrides.
Each profile sets an initial query budget (baseline 18, enhanced 35, deep 65); every live search or
page retrieval costs 1, and the adaptive controller stops/escalates within that budget. A budget-
exhausted stop is recorded honestly with the remaining gaps flagged.

## 7. Setup & run

### Windows (PowerShell)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```
Or simply: `./run.ps1` (launch) / `./run.ps1 -Test` (tests).

### Linux / macOS
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```
Or: `./run.sh` (launch) / `./run.sh test` (tests).

### First steps in the UI
1. **Vendor Inventory → "Use bundled sample workbook"** (or upload your own `.xlsx`/`.csv`).
2. Select vendors + depth profile → **Run investigation(s)**.
3. Review **Vendor Intelligence / Evidence / Adaptive OSINT / Risk**.
4. **Freeze** each vendor on Vendor Inventory.
5. **Benchmark Evaluation** → unlock → run evaluation.
6. **Export Center** for CSV/JSON/Excel/Markdown artifacts.

## 8. Tests
```bash
python -m pytest -v
```
Covers imports, connectors (external APIs mocked — no paid calls), evidence, adaptive control, risk
scoring, database/migrations, end-to-end offline workflow, exports, Streamlit page execution, and the
**mandatory benchmark-isolation** suite.

## 9. Troubleshooting
- **`py -3.11` not found** – install Python 3.11+, or set `PYTHON` env var for `run.sh`.
- **Streamlit shows OFFLINE** – expected without a search key; add `BRAVE_SEARCH_API_KEY` to `.env`.
- **SEC connector unavailable** – set `SEC_CONTACT_EMAIL` (fair-access requirement).
- **`database is locked`** – close other processes using `data/meridian.db`; WAL mode is enabled.
- **Benchmark page locked** – you must freeze at least one snapshot first, then unlock explicitly.

## 10. Limitations
- Offline mode cannot discover public AI usage; absence of findings ≠ absence of AI use.
- Infrastructure connectors (SecurityTrails/Censys/Shodan) are **stubs** — labelled as such, never faked.
- The benchmark PDF parser is best-effort on a 113-page, variably-formatted document; a vendor whose
  verdict cannot be confidently located is reported as **incomparable** rather than guessed.
- Deterministic signal detection is keyword-based; an LLM key improves (advisory) nuance only.
- Keep findings inside this exercise (the input workbook concerns real organisations).
