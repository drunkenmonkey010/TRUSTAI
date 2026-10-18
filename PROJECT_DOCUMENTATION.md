# Meridian Vendor AI Intelligence Engine — Full Project Documentation

> Interview-ready reference. Read top-to-bottom once; use the Q&A at the end to rehearse.
> Everything here reflects the code as actually built — file names, functions and numbers are real.

---

## 0. One-paragraph pitch (say this first)

"Meridian is a runnable Python/Streamlit system that investigates a company's third-party vendors
using only public information, figures out what can actually be *substantiated* about each vendor's
AI usage and data flows, scores the third-party AI-security risk with a transparent deterministic
model, and adapts how deep it investigates based on each vendor's business criticality. Every
conclusion is traced back to a cited source. Crucially, it validates itself against an independently
researched benchmark that is kept strictly isolated — locked until our own results are frozen — so the
benchmark can honestly reveal what we missed. It's not a dashboard of hardcoded answers; it's an
evidence engine with honest uncertainty."

---

## 1. The problem and the brief

**Context:** Meridian Financial (a fictional bank in the case study) has a portfolio of third-party
vendors — core banking, payments, document services, etc. Some of these vendors may use AI, and if
they process Meridian's data through AI features, that creates a new category of third-party risk
(data leaving to model providers, training on customer data, undocumented sub-processors).

**The task (Optiv Case Study 01):** Build a solution that:
1. Investigates each vendor using **permitted public OSINT** (no vendor contact, no intrusion).
2. Determines **what can be substantiated** about AI usage — not rumor, not marketing.
3. Assesses **third-party AI-security risk** per vendor.
4. Adapts **investigation depth** to uncertainty and criticality.
5. Preserves **verifiable evidence** and generates **actionable recommendations**.
6. Keeps a held-out benchmark (`OPTIV.pdf`) **isolated** and uses it only to **evaluate** the system.

**Two input files:**
- `Meridian_Vendor_Input.xlsx` — the operational input (6 real vendors V-001..V-006 + one fictional
  worked example V-000). Columns A–K are provided; L onward are the analyst's job.
- `OPTIV.pdf` — the **benchmark / answer key** (independently researched). It is NOT an investigation
  source; it is held out to grade the automated run.

---

## 2. Solution overview and design philosophy

The system is an **agentic OSINT pipeline** wrapped in an analyst UI, with five non-negotiable
principles baked into the architecture:

1. **Evidence or it didn't happen.** Every material claim references ≥1 evidence record with a URL,
   an exact excerpt, a content hash, and publication/retrieval dates. Claims with no evidence are
   flagged *unsupported* and sent to QA.
2. **Honest uncertainty.** "Unknown" is never silently turned into "zero risk" or "proof of a
   problem." Inherent risk, residual risk, evidence confidence and investigation uncertainty are
   four **separate** numbers.
3. **Deterministic core.** The risk score is computed by code from validated structured inputs. An
   LLM, if configured, may *propose* a label, but it never sets a number.
4. **Adaptive, not fixed.** Depth is driven by criticality and remaining uncertainty, not a rule like
   "always do 10 searches."
5. **Benchmark integrity.** The answer key is isolated by architecture *and* automated tests; it can
   only be opened after results are frozen, and it can never alter those results.

---

## 3. Strategy — how the approach was reasoned

- **Separate "what the vendor does" from "what Meridian knows it does with AI."** Criticality is a
  business-impact judgment from the operational input; AI usage is an OSINT evidence question. They
  are computed by different agents and never conflated.
- **Criticality drives depth.** A Critical core-banking vendor deserves the full seven-layer
  investigation; a Medium reporting vendor does not. So the system derives criticality first, then
  chooses depth automatically.
- **Targeted collection, not crawling.** OSINT is expensive and noisy. The strategy agent writes a
  bounded, layered query plan and the adaptive controller stops when evidence is sufficient or the
  budget is spent.
- **First-party beats repetition.** Ten blogs repeating one press release is not corroboration. The
  verification layer detects circular reporting and down-weights it.
- **Fail honest.** If there's no search key and no analyst-supplied source, the right answer for a
  real vendor is "Insufficient evidence" — not a guess. The benchmark then exposes that as a miss.

---

## 4. Technology stack (and why each piece)

| Layer | Tech | Why |
|---|---|---|
| UI | **Streamlit** | Fast to build a multi-page analyst workbench; pure Python. |
| Data validation | **Pydantic / pydantic-settings** | Typed schemas for evidence, connector results, settings. |
| Workbook / data | **pandas + openpyxl** | Read the `.xlsx`, flexible import, exports. |
| Persistence | **SQLite (stdlib sqlite3)** | Zero-setup, file-based, no cloud dependency; WAL mode, FK on. |
| HTTP | **httpx** | Modern client; timeouts, redirects, retries. |
| HTML parse | **BeautifulSoup (+lxml)** | Extract readable text from retrieved pages. |
| PDF | **pypdf** | Parse the benchmark PDF (benchmark workflow only). |
| Graph | **networkx** | Vendor→provider relationship graph. |
| Charts | **plotly** | Interactive charts in the UI. |
| Tables/export | **tabulate** | Markdown table exports. |
| Tests | **pytest** | 154 tests incl. the mandatory isolation suite. |
| LLM (optional) | **OpenAI-compatible abstraction** | Advisory classification only; app runs without it. |

**Why not a heavyweight agent framework?** The 12 agents are small, typed Python units run by a
lightweight orchestrator. This keeps everything debuggable, testable and free of hidden control flow.

---

## 5. Project structure (what each module does)

```
meridian-vendor-ai-intelligence-engine/
├── app.py                     # Streamlit entry (home page)
├── ui_common.py               # shared UI helpers (db, registry, mode banner)
├── pages/                     # 9 analyst pages (1_Executive_Overview … 9_Export_Center)
├── config/
│   ├── settings.py            # env-based Settings (pydantic), secret_status(), offline_mode
│   └── logging_config.py      # structured logging + secret redaction filter
├── database/
│   ├── schema.py              # 20 tables as versioned migrations (user_version)
│   └── connection.py          # Database wrapper: connect(), query(), insert(), audit(), settings
├── imports/
│   ├── workbook.py            # flexible .xlsx/.csv import, field mapping, persistence
│   └── normalization.py       # name/id normalization, duplicate detection
├── connectors/
│   ├── base.py                # BaseConnector (cache, rate-limit, retries, run recording), ConnectorResult
│   ├── _http.py               # request_with_retries (backoff, 429/5xx)
│   ├── brave_search.py        # primary web search
│   ├── tavily_search.py       # alternative web search
│   ├── public_web.py          # direct page retrieval (robots-aware)
│   ├── sec_edgar.py           # SEC filings connector
│   ├── opencorporates.py      # legal-entity enrichment
│   ├── infrastructure.py      # SecurityTrails/Censys/Shodan — labelled stubs
│   ├── config.py              # connector catalogue + specs
│   └── registry.py            # instantiation, health, live/offline mode, selection
├── evidence/
│   ├── schemas.py             # Pydantic: SourceRecord, Claim, EvidenceRecord, enums, labels
│   ├── provenance.py          # canonicalize_url(), content_hash(), file_hash()
│   ├── ledger.py              # EvidenceLedger: record sources/claims/evidence, dedup, queries
│   └── verification.py        # evidence quality score, circular + contradiction detection
├── agents/
│   ├── base.py                # BaseAgent (records agent_runs), InvestigationContext, QueryBudget
│   ├── llm.py                 # provider-agnostic LLMClient (advisory)
│   ├── signals.py             # deterministic keyword signal analysis (AI/genAI/providers/…)
│   ├── vendor_intake.py       # Agent 1
│   ├── criticality.py         # Agent 2 (12 dimensions)
│   ├── osint_strategy.py      # Agent 3 (layer plan, budgets, auto-depth resolution)
│   ├── collection.py          # Agent 4 (live/offline/sample collection)
│   ├── evidence_extraction.py # Agent 5
│   ├── evidence_verification.py # Agent 6
│   ├── ai_classification.py   # Agent 7 (8 labels, deterministic)
│   ├── provider_dataflow.py   # Agent 8
│   ├── adaptive_depth.py      # Agent 9 (drives the layer loop)
│   ├── risk_assessment.py     # Agent 10
│   ├── recommendations.py     # Agent 11
│   └── quality_assurance.py   # Agent 12
├── orchestration/
│   ├── workflow.py            # InvestigationWorkflow: runs agents, resolves auto-depth, summary
│   ├── run_manager.py         # run lifecycle + freeze_snapshot (hash) + verify_snapshot_hash
│   ├── adaptive_controller.py # AdaptiveController.decide() — continue/stop/escalate
│   └── scheduler.py           # batch over several vendors
├── risk/
│   ├── weights.py             # DEFAULT_WEIGHTS, MODEL_VERSION, UNKNOWN_POLICY, validate_weights
│   ├── scoring.py             # compute_risk() — deterministic
│   └── explanations.py        # human-readable risk explanation
├── benchmark/
│   ├── access_control.py      # BenchmarkAccessController (the only gateway), states, audit
│   ├── pdf_parser.py          # parse_benchmark() — anchors, verdicts
│   ├── evaluator.py           # BenchmarkEvaluator — compare frozen snapshot vs benchmark
│   └── schemas.py             # BenchmarkRecord, EvaluationItem, EvaluationMetrics
├── reports/                   # vendor_report.py, portfolio_report.py
├── exports/export_manager.py  # CSV/JSON/Excel/Markdown exports
├── tests/                     # 14 test files (154 tests)
├── samples/                   # the sample workbook + offline_sources.json (labelled SAMPLE)
└── data/benchmark_protected/OPTIV.pdf   # the held-out benchmark
```

---

## 6. Data model (SQLite, 20 tables)

Operational, evidence and benchmark data live in **separate tables** on purpose.

- **Operational input:** `vendor_imports`, `vendors`
- **Lifecycle:** `investigation_runs`, `agent_runs`, `investigation_queries`, `connector_runs`
- **Evidence & findings:** `sources`, `claims`, `evidence`, `vendor_relationships`,
  `ai_usage_classifications`, `data_flow_findings`, `risk_assessments`, `recommendations`,
  `adaptive_decisions`
- **Frozen results:** `frozen_snapshots`
- **Benchmark (separate):** `benchmark_records`, `benchmark_evaluations`
- **Cross-cutting:** `audit_events` (append-only), `application_settings`

Key design points:
- **Migrations** are an ordered list in `database/schema.py`; the runner applies any migration whose
  version > SQLite's `PRAGMA user_version`. Idempotent and re-openable.
- **`audit_events`** is append-only: every user action, connector error, adaptive decision, snapshot
  freeze, benchmark unlock/access/evaluation is logged. Secrets are never logged.
- **`frozen_snapshots`** stores a JSON payload of the findings plus a **SHA-256 content hash**, a
  timestamp, run id and schema version — the immutable record.

---

## 7. Configuration and secrets

`config/settings.py` is a pydantic-settings `Settings` class read from the environment / `.env`:
- Secrets (`BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, `OPENAI_API_KEY`, …) are read but **never
  returned** by `secret_status()` — only a boolean "configured" per provider.
- `offline_mode` = `not any_live_search` (true when no Brave/Tavily key).
- `llm_enabled` = provider is openai **and** a key is present.
- Budgets, timeouts, user-agent, robots behaviour are all configurable.
- `logging_config.py` adds a **redaction filter** that strips anything key-shaped from logs.

**Interview line:** "Secrets never touch logs, the DB, or the UI — only a per-provider boolean."

---

## 8. Connector architecture — how APIs are actually called

This is the part interviewers probe. Flow for any connector call:

```
agent → registry.get("brave_search").run(query, vendor_id, run_id)
         └─ BaseConnector.run():
              1. cache check (per query+kwargs)      → return cached if hit
              2. is_available()?  (key present?)     → if not: status=OFFLINE, return [] (NO fabrication)
              3. rate limiter .wait()                → throttle to CONNECTOR_RATE_LIMIT_PER_SEC
              4. self._run(...)  (the real API call) → provider-specific
              5. record a connector_runs row (status, http_status, latency, errors)
              6. cache + return List[ConnectorResult]
```

- **`_http.request_with_retries`** does timeouts + **exponential backoff** (0.75·2^n), retrying on
  transport errors, HTTP 5xx and 429 (rate-limited), up to `HTTP_MAX_RETRIES`.
- **Normalization:** every connector returns `ConnectorResult` (Pydantic) with a fixed field set:
  `connector_name, query, vendor_id, retrieved_at, url, canonical_url, title, published_at,
  source_type, source_owner, snippet, extracted_text, http_status, retrieval_status, content_hash,
  is_sample, error_code, error_message, metadata`. Unavailable fields are left null — never invented.
- **Never fabricates:** on failure/offline, returns `[]` or a result with an honest
  `retrieval_status` (error / offline / unavailable / inaccessible) and records it.

**Each connector specifically:**
- **Brave** (`brave_search.py`): `GET https://api.search.brave.com/res/v1/web/search`, header
  `X-Subscription-Token: <key>`, params `q`, `count`. Parses `web.results[]` → title/url/description.
- **Tavily** (`tavily_search.py`): `POST https://api.tavily.com/search`, JSON body with `api_key`,
  `query`, `max_results`. Parses `results[]`.
- **public_web** (`public_web.py`): httpx GET with a descriptive User-Agent; checks `robots.txt`
  first (if `RESPECT_ROBOTS_TXT`); extracts readable text via BeautifulSoup (strips script/style/nav);
  marks 401/402/403 and CAPTCHA pages as `inaccessible`. **Does not bypass auth/paywalls/CAPTCHAs.**
  Treats page text as **untrusted data**, never as instructions.
- **SEC EDGAR** (`sec_edgar.py`): no key, but SEC's fair-access policy requires a descriptive
  User-Agent with contact info (`SEC_CONTACT_EMAIL` gates availability). Loads
  `company_tickers.json` → fuzzy-matches the vendor name to a CIK → fetches
  `data.sec.gov/submissions/CIK##########.json` → recent filings. Fails gracefully if no company
  matches (not every vendor is a reporting company).
- **OpenCorporates** (`opencorporates.py`): company search; distinguishes exact vs probable vs
  ambiguous matches; corporate registration is **never** treated as evidence of AI usage.
- **Infrastructure** (`infrastructure.py`): SecurityTrails/Censys/Shodan are **clearly-labelled
  integration stubs** — if a key is present they still return `unavailable` with
  `error_code=stub_not_implemented` rather than faking data. Guardrail embedded: infrastructure
  association ≠ ownership ≠ data processing.

**Registry** (`registry.py`): instantiates connectors, runs health checks, reports
`execution_mode()` = "live"/"offline", and `select_search_connector()` prefers Brave then Tavily.
Per-connector enable/disable is stored in `application_settings`.

---

## 9. Evidence model — how evidence is collected and trusted

The system draws a hard line between five kinds of statement (enum `ClaimType`):
**observation → extracted claim → inference → risk judgment → recommendation.**

**Collection → Evidence pipeline:**
1. **Collection (Agent 4)** executes the layer's planned queries (live) or uses analyst-supplied /
   sample sources (offline), and writes **`sources`** rows via the ledger. Dedup is by
   `canonical_url + content_hash` (so the same page from two connectors is one source).
2. **Extraction (Agent 5)** runs `agents/signals.analyze_text()` over each source's text. This is a
   **deterministic keyword scanner** that finds AI / generative / integration / data-flow / retention
   phrases, named providers (OpenAI, Anthropic, AWS Bedrock…), and deployment status (released/beta/
   planned/discontinued), each with the **exact surrounding excerpt**. For each salient category it
   writes a `claims` row and an `evidence` row linking claim→source with the excerpt, marking
   **direct** (first-party statement) vs **inferred** (e.g. a careers page implying AI work).
3. **Verification (Agent 6)** scores each evidence item and updates it:
   - `score_evidence()` = weighted blend of **authority** (first-party / independent / aggregator /
     unknown), **directness** (direct/indirect), **freshness** (from publication date), and
     **independence**.
   - `detect_circular_reporting()` flags evidence sharing a content hash (duplicate/circular).
   - `detect_contradictions()` flags claims that have both supporting and contradicting evidence.
   - `independent_corroboration_count()` counts distinct non-circular independent sources.

**Provenance** (`evidence/provenance.py`): `canonicalize_url()` (lowercases host, strips tracking
params, trailing slash) and `content_hash()` (SHA-256 of normalized text) make dedup deterministic;
`file_hash()` hashes the benchmark file for integrity.

**Rule enforced:** a claim becomes `supported=1` only when it has ≥1 **supporting** evidence row;
otherwise `EvidenceLedger.unsupported_claims()` returns it and QA flags it.

**Interview line:** "Publication date and retrieval date are stored separately — when the content was
written vs when we fetched it — so freshness is honest."

---

## 10. The 12 agents (purpose · inputs · outputs · logic)

All agents extend `BaseAgent`, which records an `agent_runs` row (status, timestamps, retries,
current action, JSON output) so the Agent Monitor shows **real** progress, not a fake bar.

1. **Vendor Intake & Identity** — normalizes the record, extracts aliases (e.g. "FSSI" from
   parentheses), spots parent-company hints, records identity ambiguities, writes the initial
   profile + an observation claim grounded in the operational record. *Never merges two orgs on a
   similar name.*
2. **Business Criticality** — the **12-dimension** assessment (see §12). Derives a tier
   (Critical/High/Medium/Low) from the operational input, each dimension scored 0–3 with
   known/partial/unknown status. Persists the derived tier to the vendor.
3. **OSINT Strategy** — writes investigation questions + hypotheses and a **bounded, layered query
   plan** (each query tagged with a rationale), capped by the profile's `max_layer`. Also exposes
   `resolve_profile()` for auto-depth.
4. **Public OSINT Collection** — executes the current layer's queries. **Live:** search connector +
   page retrieval of top results. **Offline:** analyst-supplied sources, plus clearly-labelled
   SAMPLE sources for the fictional example vendor only. Records failures honestly.
5. **Evidence Extraction** — claims + cited excerpts from each new source (see §9).
6. **Evidence Verification** — quality score, circular/duplicate + contradiction detection (see §9).
7. **AI-Usage Classification** — deterministic rules over verified evidence → one of **8 labels**
   (see §13). An LLM may propose a label (recorded as advisory) but never overrides the rule.
8. **Provider & Data-Flow Analysis** — builds `vendor_relationships` (vendor→AI provider, confirmed
   vs probable) and a `data_flow_findings` row. **Never** claims customer data flows to a provider
   unless documented — customer-data involvement defaults to `unknown`.
9. **Adaptive Depth Controller** — drives the layered loop (see §11/§13). For each layer it runs
   Collection→Extraction→Verification, asks the controller continue/stop/escalate, and records an
   `adaptive_decisions` row. Tracks layer coverage separately from quality.
10. **Risk Assessment** — assembles validated inputs and calls `compute_risk()` (see §14). Stores the
    assessment with model version, weights and dimension scores.
11. **Recommendations** — prioritised, role-assigned, closure-conditioned actions **scaled by
    criticality + gaps** (see §15).
12. **Independent QA** — checks for unsupported claims, missing citations, misclassification,
    unsupported relationships, contradictions, overconfidence, premature stopping, repeated searches,
    and **benchmark contamination** (via the audit log). Flags the run ok / review / unreliable.
    *It cannot access the benchmark file.*

---

## 11. Seven-layer adaptive OSINT methodology

Layers (the strategy agent plans queries per layer; the controller advances through them):
1. **Identity & baseline** — official domain, products, parent, trust resources.
2. **AI signal discovery** — does the vendor publicly mention AI / generative AI / copilots?
3. **Product & technical validation** — is the feature released/beta/planned/discontinued? relevant?
4. **Provider & dependency mapping** — named model providers, subprocessors, integrations.
5. **Data-flow & processing** — what data is documented as processed? customer data? retention/training?
6. **Corroboration & contradiction** — independent confirmation; conflicting or superseding evidence.
7. **Risk-oriented gap closure** — the highest-impact unresolved question; analyst/questionnaire.

Each layer records coverage, evidence quality, uncertainty and an exit rationale. **Completing layers
is tracked separately from investigation quality** — the system never equates "did 7 layers" with
"did a good job."

---

## 12. Criticality — the 12 dimensions (Agent 2)

From the **operational input only** (never the benchmark, never live OSINT), each dimension is scored
0–3 with a basis and a known/partial/unknown status:

1. Business Function Centrality · 2. System-of-Record / Process-of-Authority Dependency ·
3. Failure Blast Radius · 4. Time Criticality · 5. Workaround Availability · 6. Recoverability ·
7. Transaction Integrity Criticality · 8. Data Consequence · 9. Exit & Substitutability ·
10. Regulatory / Compliance Criticality · 11. Financial Materiality · 12. Concentration / Dependency Risk.

**Aggregation rubric:** mean of the 12 scores + count of dimensions rated Critical (≥3):
- `critical_count ≥ 5` or `mean ≥ 2.3` → **Critical**
- `critical_count ≥ 3` or `mean ≥ 1.7` → **High**
- `mean ≥ 1.1` → **Medium** · else **Low**

**Actual portfolio result:** Fiserv/BNY/Clearing House/FSSI → Critical; AutomWorx → High (matches the
benchmark's recommended HIGH); Terrapin → Medium.

**Auto-depth:** `resolve_profile()` maps the tier to a profile — Critical/High→**deep**,
Medium→**enhanced**, Low→**baseline** — with per-profile query budgets 18 / 35 / 65.

---

## 13. AI-usage classification (Agent 7) — claim-level, 11 labels (V2.1)

**The V2.1 fix for keyword false-positives.** A keyword match is a *discovery signal only*; it never
by itself establishes confirmed AI use. Classification is **claim-level and context-aware**
(`evidence/claim_classifier.py`):

1. **Per-claim classification (Agent 5):** for each AI signal hit, `classify_claim()` analyses the
   surrounding excerpt and resolves the **context** — product capability vs policy / general
   discussion / marketing / planned feature / historical-discontinued / customer-controlled
   integration / third-party partnership / job advert — plus temporal scope, deployment status,
   data-flow implication, directness and authority. It only returns a **Confirmed** label for a
   **first-party, present-tense, functional capability** (a stated AI action in the product).
2. **Independent verification (Agent 7):** `verify_support()` re-checks every confirmed claim — it is
   **downgraded** to "AI mention only" unless the excerpt is first-party, states a functional
   capability, and has no negating / future / historical / policy / customer-controlled markers. The
   original claim and the downgrade rationale are preserved.
3. **Vendor-level aggregation:** the label is the **strongest *verified* claim** by precedence
   (`AI_LABEL_PRECEDENCE`). Keyword mentions aggregate to **AI mention only**, never to confirmed.

**Labels (11):** Confirmed AI use · Confirmed generative AI use · Confirmed AI product integration ·
Confirmed AI product feature · Third-party AI relationship confirmed · AI capability advertised;
deployment unverified · AI use indicated by indirect evidence · **AI mention only** · AI use not
established · Conflicting evidence · Insufficient evidence.

**Worked proof (end-to-end):** a vendor page that only *mentions* AI in a policy →
**"AI mention only"** (confidence 0.15); a page stating *"uses AI to automatically detect and
summarise fraud alerts in real time"* → **Confirmed generative AI use** (0.75).

A public AI feature does **not** by itself establish that a particular customer's data is processed by
it — that is Agent 8's separate question. Per-claim structured fields (classification, context_label,
deployment_status, temporal_scope, data_flow_implication, confidence, rationale, verification_status,
review_status) are persisted on the `claims` table (schema migration v2).

---

## 14. Risk scoring (Agent 10 + `risk/`) — deterministic math

**Dimensions & default weights** (`risk/weights.py`, sum to 1.0):
vendor_criticality 0.20 · data_sensitivity 0.18 · ai_usage_exposure 0.16 ·
provider_transparency_gap 0.12 · data_flow_uncertainty 0.12 ·
retention_training_uncertainty 0.10 · unresolved_contradictions 0.06 · security_governance_gap 0.06.

**Pipeline (`compute_risk`):**
1. Map categorical inputs to [0,1] (criticality tier, data-sensitivity keywords, AI label, etc.).
2. **Unknown policy:** a missing dimension takes a *documented* elevated value (e.g. undocumented
   data flow → 0.7), is added to `missing_information`, and is **never** treated as 0.
3. `inherent_risk = Σ(score·weight) · 100`.
4. `evidence_confidence = 0.6·mean_evidence_quality + 0.4·min(1, corroboration/3)`.
5. `investigation_uncertainty = f(unknown fraction, open questions, 1−confidence)`.
6. `residual_risk = inherent·0.8` **only if** control evidence exists (trust centre/SOC2/DPA found);
   otherwise `None` — you can't justify a reduction without evidence of controls.
7. `overall_priority` from bands (≥80 Critical, ≥60 High, ≥40 Medium, else Low), bumped up when a
   Critical vendor has high uncertainty.
`explain()` renders the full breakdown (score × weight per dimension + missing info).

**The four numbers are separate on purpose:** inherent (before controls), residual (after proven
controls), evidence confidence (how good the evidence is), investigation uncertainty (how much is
unknown). Interviewers love that distinction.

---

## 15. Recommendations (Agent 11) and QA (Agent 12)

**Recommendations** scale with criticality + the actual gaps, each tied to a finding, categorised as
immediate control / governance / technical validation / evidence collection / monitoring, with
priority (Immediate→Low), owner, time horizon and closure conditions. A Critical confirmed-AI vendor
produces ~8 (questionnaire, Risk-Committee escalation, contract clauses, subprocessor registration,
retention terms, provider data-path validation, security docs, periodic reassessment); an
insufficient-evidence Medium vendor produces ~2 (monitoring).

**QA** independently reviews the run and can flag it **unreliable**. It verifies, among other things,
that no benchmark access event is associated with the run (contamination check via audit log).

---

## 16. Benchmark isolation — the integrity story

**Why:** the benchmark is the answer key. If the investigation could read it, the evaluation would be
meaningless. So isolation is enforced two ways.

**Architecture:** all benchmark access goes through **one** gateway, `BenchmarkAccessController`:
- The benchmark file path lives **only** in that module (not in any agent/connector config).
- States: **LOCKED** (default) / **UNLOCKED**, stored in `application_settings`.
- `benchmark_path()` raises `BenchmarkLockedError` unless unlocked, and **audits** every access.
- `unlock(reason)` **requires a valid frozen snapshot to already exist** — otherwise it's blocked
  with an explanation. Every unlock is audited.

**Freeze:** `RunManager.freeze_snapshot()` collects all findings into a JSON payload, computes a
**SHA-256** content hash, stores it in `frozen_snapshots` with a timestamp/run id/schema version, and
sets the run status to `frozen`. `verify_snapshot_hash()` re-hashes and compares — tamper-evident.

**Evaluation:** `BenchmarkEvaluator`:
- Parses the PDF via `pdf_parser.parse_benchmark()` — segments the 113-page doc by vendor **anchors**
  (both IDs like "V-005" and names/acronyms like "BNY"), assigns the explicit "AI usage detected:
  YES/No/Inconclusive" verdict to the nearest preceding anchor, and extracts named providers + risk
  class per vendor.
- Reads each vendor's **frozen snapshot read-only**, maps the automated label to yes/no/inconclusive,
  and compares: **exact / partial / missed / false_positive / incomparable**, plus providers and risk
  dimensions and a **confidence-calibration** (overconfidence) check.
- Computes **precision / recall / F1** treating benchmark "yes" as positive.
- **Never modifies the snapshot.**

**Enforced by tests** (`tests/test_benchmark_isolation.py`, all pass): locked before freeze; unlock
blocked without a snapshot; locked after freeze until explicit unlock; loader rejects unauthorized
access; evaluation doesn't change the snapshot hash; benchmark doesn't alter queries or risk; every
unlock/eval audited; snapshot hash tamper-evident; and a **static AST test** proving no module under
`agents/ connectors/ orchestration/ risk/ evidence/ imports/` imports the `benchmark` package.

---

## 17. End-to-end workflow (sequence)

```
import_file(xlsx) → vendors table
InvestigationWorkflow.investigate(vendor, profile="auto"):
  create_run (provisional budget) → mark_running
  PHASE 1: VendorIntake → Criticality          (no network, no budget spent)
  resolve_profile("auto", tier) → set profile + budget (deep/enhanced/baseline)
  PHASE 2: OsintStrategy (plan queries per layer)
           AdaptiveDepth loop:
             for each layer:  Collection → Extraction → Verification → controller.decide()
           AiClassification → ProviderDataflow → RiskAssessment → Recommendations → QA
  complete_run (summary)
→ UI: review  →  RunManager.freeze_snapshot()  (hash)
→ BenchmarkAccessController.unlock(reason)  (requires snapshot)
→ BenchmarkEvaluator.evaluate()  (precision/recall/F1, matches) — snapshot untouched
→ ExportManager → CSV/JSON/Excel/Markdown
```

**Adaptive controller decision rules** (`AdaptiveController.decide`): budget exhausted → **stop**;
contradictions and layer<6 → **escalate** to the corroboration layer (+ human-review flag); reached
max layer → **stop**; confirmed + no contradictions + layer≥3 → **stop early** *unless* a
Critical+sensitive vendor still has an unknown data flow → **continue** deeper; last layer produced
nothing and vendor not critical → **stop** (diminishing returns); otherwise → **continue** one layer.
Every decision is stored with a rationale.

---

## 18. The Streamlit UI (9 pages)

1. **Executive Overview** — portfolio counts, AI-label & priority distributions, connector health.
2. **Vendor Inventory** — import + field mapping + validation + duplicates; run investigations
   (depth = **auto** by default); **Freeze** results.
3. **Agent Monitor** — real agent statuses, connector requests, budget consumption, human-review flag.
4. **Vendor Intelligence** — profile, AI classification, relationship **graph**, data-flow finding,
   the 12-dimension criticality breakdown, key claims.
5. **Adaptive OSINT Explorer** — queries per layer, continue/stop/escalate decisions, stop rationale,
   reopen conditions, quality signals (separate from layer count).
6. **Evidence Explorer** — claims, evidence (filter by authority), sources, unsupported claims,
   retrieval failures; open a claim to see its cited excerpts.
7. **Risk & Recommendations** — inherent vs residual, confidence vs uncertainty, contribution chart,
   editable/versioned weights, prioritised recommendations.
8. **Benchmark Evaluation** — locked until freeze; explicit unlock; precision/recall/F1; per-item
   matches; missed/false-positive/overconfidence tables.
9. **Export Center** — all artifacts in CSV/JSON/Excel/Markdown, each stamped with run id, timestamp,
   model version and a limitations note.

---

## 19. Testing

`python -m pytest -v` → **154 tests pass** (~68s). Files:
- `test_imports.py` — parsing, mapping (incl. the "id in provided" word-boundary fix), missing/empty,
  duplicates, CSV.
- `test_connectors.py` — offline without key, Brave normalization (mocked HTTP), HTTP error, **cache**
  prevents duplicate calls, infra stub never fabricates, registry offline mode.
- `test_evidence.py` — unsupported claim flagged, supporting evidence marks supported, source dedup,
  publication≠retrieval date, contradictions, source-confidence≠claim-certainty, circular detection.
- `test_criticality.py` — 12 dimensions assessed, auto-depth resolution + budget, volume parsing.
- `test_adaptive_depth.py` — budget stop, contradiction escalation, strong-evidence stop,
  critical+sensitive continue, diminishing returns, max layer, every decision has a rationale,
  end-to-end budget respected.
- `test_risk_scoring.py` — determinism, weight validation/normalization, unknown≠zero, confidence≠risk,
  residual only with controls, model version preserved.
- `test_database.py` — migrations applied/idempotent, audit append-only, settings roundtrip,
  benchmark tables separate from operational.
- `test_workflow.py` — offline example confirms AI, real vendor insufficient, all agents run, history
  preserved on rerun, snapshot hash, reproducible risk.
- `test_benchmark_isolation.py` — **the mandatory suite** (see §16).
- `test_exports.py` — CSV/JSON(meta)/XLSX/Markdown/snapshot manifest.
- `test_app_smoke.py` — all modules import, pages parse, 12 agents present, AppTest runs app.py.

External APIs are **mocked**; no test needs a paid key.

---

## 20. Results and inference

- **Fiserv (V-002), run LIVE:** classified **Confirmed generative AI use**; the benchmark says
  **yes** → **exact match**. The engine, from public evidence, independently reached the human
  analyst's conclusion.
- **Offline (no key):** every real vendor returns **Insufficient evidence** — the honest answer with
  no OSINT — and the benchmark evaluation shows **recall ≈ 0** for that run. That's the system working
  as intended: the benchmark *reveals the miss* instead of hiding it. A live run closes the gap.
- **Criticality vs benchmark:** AutomWorx → **High**, matching the benchmark's recommended tier.

**Inference for the stakeholder:** the method is sound and, when given live search, it reproduces
expert conclusions while staying honest about what it cannot yet prove (customer-data flow, named
providers, retention terms) — which is exactly what the recommendations then chase down.

---

## 21. Limitations (state these before the interviewer does)

- Offline mode can't discover AI usage — a live search key is required for real investigation.
- Infrastructure connectors (SecurityTrails/Censys/Shodan) are **labelled stubs**, not live.
- The benchmark PDF parser is **best-effort** on a 113-page, variably-formatted document; a vendor
  whose verdict can't be confidently located is reported **incomparable**, not guessed (e.g. V-005).
- Signal detection is keyword-based and deterministic; an LLM key adds only advisory nuance.
- It assists authorized OSINT/defensive risk work; it does not contact vendors or perform intrusion.

---

## 22. How to run (live vs offline)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env     # add TAVILY_API_KEY (free tier) for LIVE OSINT
streamlit run app.py            # http://localhost:8501
python -m pytest -v             # run the tests
```

- **Offline/demo:** no key → banner says OFFLINE; real vendors → "Insufficient evidence"; the
  fictional V-000 uses clearly-labelled SAMPLE sources.
- **Live:** one search key (Tavily is free, no card) → banner says LIVE; real OSINT is performed and
  cited. Brave is the preferred primary if both are set.

---

## 23. Anticipated interview questions (with crisp answers)

**Q: Walk me through the architecture.**
A: UI (Streamlit) → orchestration (workflow, run manager, adaptive controller) → 12 agents → evidence
& risk layer → SQLite. Agents reach the internet only through a connector layer; the benchmark sits
behind one locked gateway and no agent imports it.

**Q: How do you avoid hallucinating findings?**
A: Three ways. Connectors never fabricate — on failure they return empty with an honest status.
Detection is deterministic keyword scanning over *retrieved* text, with the exact excerpt stored.
Every claim must cite ≥1 evidence row or it's flagged unsupported. The risk number is computed, not
model-generated.

**Q: How is an API actually called?**
A: `BaseConnector.run()` checks the cache, checks availability (key present), rate-limits, calls the
provider via `request_with_retries` (timeouts + exponential backoff on 5xx/429), normalizes the
response into a `ConnectorResult`, and records a `connector_runs` row. Brave is a GET with an
`X-Subscription-Token` header; Tavily a POST with the key in the body; SEC EDGAR resolves a CIK then
fetches submissions with a fair-access User-Agent.

**Q: How do you decide how deep to investigate?**
A: Criticality (12 dimensions) → tier → profile (auto). Then the adaptive controller advances layer by
layer and stops on confidence, budget, or diminishing returns — escalating on contradictions. It's
evidence-driven, not a fixed search count.

**Q: What's the difference between inherent risk, residual risk, confidence and uncertainty?**
A: Inherent = risk before controls. Residual = inherent reduced *only* when there's control evidence.
Evidence confidence = how good the underlying sources are. Investigation uncertainty = how much is
still unknown. They're four separate numbers so "we're unsure" never masquerades as "it's safe."

**Q: How do you keep the benchmark honest?**
A: It's locked by default, only unlockable after a hashed snapshot is frozen, reachable through one
audited gateway, never imported by any agent (a static test proves it), and the evaluation reads the
snapshot read-only — it can reveal misses and false positives but can't change the graded result.

**Q: Why deterministic instead of "just ask an LLM"?**
A: Auditability and defensibility. A third-party risk finding has to be explainable and reproducible.
The LLM is optional and advisory; the score and the evidence trail are deterministic.

**Q: What would you do with more time?**
A: Live-run the full portfolio, add a DuckDuckGo keyless connector, make the infra connectors real,
strengthen the PDF parser, and add a vendor-questionnaire workflow for the unknown data flows the
recommendations already flag.

**Q: How does offline mode avoid lying?**
A: It never presents sample data as live OSINT (sample sources are flagged `is_sample` and only
attach to the fictional example vendor), and real vendors honestly come back "Insufficient evidence."

---

## 23a. V2.1 upgrade — new capabilities

The V2.1 upgrade extended the platform from "investigate + score" to a full assurance lifecycle. All
features are deterministic, persisted (schema migrations v2 + v3) and tested.

- **Claim-level AI classification** (§13) — the headline fix: keyword mentions never become confirmed
  use (`evidence/claim_classifier.py`, 11 labels, independent `verify_support()` downgrade gate).
- **Vendor questionnaire engine** (`questionnaires/engine.py`) — generates **gap-driven** questions
  from each run's actual unknowns (data flow, provider, retention, oversight, agent permissions,
  logging, incident notification), not a fixed giant questionnaire. `validate_response()` keeps
  **self-attestation distinct from verified evidence**.
- **Remediation & risk-decision workflow** (`remediation/manager.py`) — findings follow an audited
  **state machine** (open → … → closed/accepted_risk/reopened); closing **requires human-confirmed
  evidence**; risk acceptance **preserves the original automated conclusion**; full `finding_history`.
- **Control maturity matrix + framework crosswalk** (`frameworks/crosswalk.py`) — 13 control domains
  assessed conservatively from evidence (**'not_verified' ≠ 'absent'**), mapped to real objective
  identifiers in **NIST AI RMF, NIST CSF, ISO/IEC 27001, ISO/IEC 42001, OWASP LLM** — evidence-based,
  never a compliance/certification claim.
- **AI threat modeling + attack paths** (`threat_modeling/engine.py`) — OWASP-LLM-aligned scenarios
  generated **only when AI use is established**, each typed **plausible / hypothetical** (never an
  observed vulnerability); attack paths mark **unknown links** and assumptions explicitly.
- **Contract/policy clause analyzer** (`contracts/analyzer.py`) — clause-level findings over uploaded
  documents (treated as **untrusted data**); 14 clause categories with present/ambiguous/not_found/
  conflicting status; **'not found' ≠ 'does not exist elsewhere'**; legal-review flags, no legal
  conclusions.
- **Change detection & risk diff** (`monitoring/change_detector.py`) — versioned baselines
  (fingerprint + hash); **material vs cosmetic** change classification; dedup; never overwrites a
  prior assessment; **manual-refresh** workflow (no false "continuous monitoring" claim).
- **Supply-chain intelligence** (`reports/supply_chain.py`) — shared-provider concentration, single
  points of failure, critical dependencies, provider-change impact; **no invented edges**.
- **Evidence quality lab** (`evaluation/lab.py`) — classifier regression precision/recall/F1/
  false-positive-rate on a **labelled fixture set** (sample sizes always shown); per-run citation and
  unsupported-claim rates. Current result: **0.0 false-positive rate, recall 1.0** on the fixtures.

New UI pages (10–17): Risk Register & Remediation, Control Maturity & Framework, Questionnaires,
Contract Analysis, Threat Modeling, Change Detection, Supply-Chain Intelligence, Evidence Quality Lab
— plus a shared dark security-analyst theme. Post-processing services auto-populate after each run
(workflow `_post_process`).

## 24. Glossary

- **OSINT** — open-source intelligence: public-only investigation.
- **Evidence record** — a cited excerpt + provenance supporting one claim.
- **Snapshot** — immutable, hashed record of a run's findings (what the system found, not proof it's
  right).
- **Frozen** — run status after a snapshot is taken; precondition for benchmark unlock.
- **Inherent / residual risk** — before controls / after proven controls.
- **Circular reporting** — multiple sources repeating one original; not independent corroboration.
- **Profile** — baseline / enhanced / deep (initial budget + max layer); `auto` picks it from criticality.
```
