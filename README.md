# ShadeQueue

> Heat‑aware, auditable shade‑shelter allocation for a Phoenix transit corridor — powered by the FortyGuard Temperature API.

ShadeQueue helps a transit planner decide **where to place a limited number of new bus‑stop shade shelters**. It combines hyperlocal heat exposure from [FortyGuard](https://www.fortyguard.com/), official City of Phoenix bus‑stop attributes, and CDC/ATSDR Social Vulnerability Index (SVI) data into a **ranked, auditable portfolio** of candidate stops.

It **recommends** candidates. It does **not** authorize spending and does **not** claim any reduction in temperature, illness, or mortality. A qualified human planner owns the final decision.

Built for the **FortyGuard Hackathon'26** (Track: *Resilient Cities & Infrastructure* / *Government & Environment*). FortyGuard temperature data is central by design — remove the heatmap and ShadeQueue collapses into an ordinary ridership ranking tool.

---

## How it works

1. A planner picks a Phoenix **area of interest (AOI)**, a date/time, an analytic metric (initially `exceedance` — hours over a labeled comparison threshold), the number of shelter **slots**, and an **equity weight**.
2. The backend submits a heatmap job to FortyGuard, stores a durable `job_id`, and polls the provider until the GeoJSON heat layer is ready.
3. Heat cells are spatially joined to bus stops (`ST_Intersects`, with a documented nearest‑cell fallback). Each stop gets a heat‑exposure value, ridership, and SVI percentile.
4. A scoring formula produces a per‑stop `heat_burden`, and a **Google OR‑Tools CP‑SAT** optimizer selects the shelter portfolio under constraints (fixed slot count, existing‑shelter exclusion, optional minimum equity share).
5. The UI shows a **baseline vs. optimized** portfolio, an **audit card** per stop (raw values, normalized components, formula version, source age, reason codes), and a CSV export.

```
heat_burden_i = normalized_ridership_i × exceedance_hours_i × (1 + equity_weight × svi_percentile_i)

maximize   Σ selected_i × heat_burden_i
subject to Σ selected_i = shelter_slots
           selected_i = 0 where a shelter already exists
           selected stops meet the minimum equity share (when enabled)
```

Every result is labeled with an explicit **runtime mode** and provenance, so a demo can never quietly pass fixture data off as live.

## Architecture

Single‑origin **modular monolith**: one deployable service and one PostGIS database.

```
Browser  —  React 19 + Vite + TypeScript
         —  MapLibre map  ⇄  synchronized accessible table
                │  same-origin  /api/v1
                ▼
FastAPI modular monolith  (Python 3.12)
   ├─ FortyGuard adapter      (live client + deterministic fixtures)
   ├─ Phoenix + CDC/SVI ingestion
   ├─ Exposure scoring
   ├─ OR-Tools CP-SAT optimizer
   └─ Audit + provenance
                │
                ▼
PostgreSQL + PostGIS  (spatial joins, GiST indexes)
```

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, TypeScript, React Router, Tailwind CSS, MapLibre GL JS, TanStack Query, Zod |
| Backend | Python 3.12, FastAPI, Pydantic, httpx |
| Persistence | PostgreSQL + PostGIS, SQLAlchemy + GeoAlchemy2, Alembic |
| Optimization | Google OR‑Tools (CP‑SAT) |
| Geometry | Shapely + pyproj (runtime), GeoPandas (ETL only) |
| Tests | pytest (backend), Vitest + Testing Library (frontend), Playwright (browser) |
| Packaging | Docker multi‑stage build |
| Deployment | Railway app service + PostGIS service |

## Repository layout

```
ShadeQueue/
├─ apps/
│  ├─ web/                        # React 19 + Vite + TS frontend
│  │  └─ src/
│  │     ├─ pages/                # ScenarioBuilder, Scenario, Portfolio, NotFound
│  │     ├─ components/           # AppShell + ui/ primitives
│  │     ├─ lib/                  # API client, helpers
│  │     └─ data/
│  └─ api/                        # FastAPI backend
│     ├─ app/
│     │  ├─ api/                  # routes/, schemas, presenters, deps
│     │  ├─ domain/               # aoi, scoring, reason_codes, runtime_mode, errors
│     │  ├─ integrations/fortyguard/   # client, schemas, fixture_provider
│     │  ├─ optimizer/            # ridership baseline + CP-SAT model
│     │  ├─ services/             # heat_jobs, portfolio, spatial, snapshots, audit, export_csv
│     │  ├─ db/                   # models, session, base
│     │  ├─ config.py, main.py, static.py, runtime.py
│     │  └─ ...
│     ├─ tests/
│     └─ serve.py                 # local dev entry point
├─ scripts/                       # generate_fixtures, load_fixtures, ingest_phoenix, ingest_svi
├─ fixtures/                      # deterministic demo data (GeoJSON + provider fixtures)
├─ migrations/                    # Alembic
├─ docs/backend.md                # backend implementation notes
├─ compose.yaml                   # local PostGIS (host port 55432)
├─ Dockerfile                     # multi-stage production image
├─ alembic.ini · ruff.toml · package.json
└─ SHADEQUEUE_TECH_STACK_PLAN.md  # full architecture + claim boundaries
```

## Prerequisites

- **Docker** (for local PostGIS via `compose.yaml`)
- **Node.js 22+** and npm
- **Python 3.12** and [**uv**](https://docs.astral.sh/uv/)

## Quickstart (local development)

Clone, then configure the backend environment:

```bash
cp .env.example .env
```

`.env` is gitignored — never commit secrets. Fixture mode works with no API key; leave `LIVE_PROVIDER_ENABLED=false` to run entirely on deterministic demo data.

**1 — Database** (once):

```bash
docker compose up -d                                       # PostGIS on localhost:55432
uv sync --project apps/api                                 # create the Python 3.12 venv
npm install
uv run --project apps/api alembic upgrade head             # apply schema
uv run --project apps/api python scripts/load_fixtures.py  # load demo data
```

**2 — Serve API + UI from one origin:**

```bash
npm run serve                                              # builds the SPA, then http://127.0.0.1:8000
```

The same FastAPI process answers `/api/*` and the planner UI. Skip a rebuild with `SKIP_FRONTEND_BUILD=1`.

Hot-reload frontend during UI work (terminal B): `npm run dev` at http://localhost:5173, which proxies `/api` to port 8000.

- App (API + SPA): http://127.0.0.1:8000
- Interactive API docs: http://127.0.0.1:8000/api/docs
- Vite HMR (optional): http://localhost:5173
- PostGIS: `localhost:55432` (user/pass/db all `shadequeue`)

## Runtime modes

Every heat result carries one explicit, visible mode derived from stored facts — never from what the caller asked for:

| Mode | Meaning |
|---|---|
| `LIVE` | A live FortyGuard result served within its own job lifecycle. |
| `CACHED_LIVE` | A previous live result being reused (deduplicated by request hash). |
| `DEMO_FIXTURE` | Produced by the deterministic fixture provider. Stays a fixture forever. |

Live mode requires **both** `LIVE_PROVIDER_ENABLED=true` **and** a non‑empty `FORTYGUARD_API_KEY`. A misconfigured live deployment falls back to fixtures and says so in the mode badge, rather than returning fixture‑shaped success under a live label.

## Configuration

Full list with inline documentation lives in [`.env.example`](.env.example). Key variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostGIS connection string (`postgresql+psycopg://…`). |
| `FORTYGUARD_API_KEY` | **Server‑side only.** Never exposed to the browser, logs, URLs, or errors. |
| `FORTYGUARD_BASE_URL` | Provider base URL (default `https://api.fortyguard.com`). |
| `LIVE_PROVIDER_ENABLED` | Master switch. `false` ⇒ every job is served by fixtures, no outbound calls. |
| `MAX_LIVE_JOBS_PER_DAY` / `…_PER_CLIENT_PER_DAY` | Credit / abuse caps for the public demo. |
| `MAX_AOI_AREA_KM2` | Rejects AOIs larger than the permitted area. |
| `ALLOWED_DATE_MIN` / `ALLOWED_DATE_MAX` | Approved analysis date window. |
| `MAP_STYLE_URL` | Public map style (not a secret; check tile provider attribution terms). |
| `CORS_ALLOW_ORIGINS` | Allowed browser origins for the API. |

## Testing & quality

```bash
# Backend
uv run --project apps/api python -m pytest apps/api/tests
uv run --project apps/api ruff check apps/api scripts migrations

# Frontend
npm run lint
npm run typecheck
npm test
```

Integration tests that need PostGIS skip themselves when `DATABASE_URL` is unreachable, so the unit suite still runs on a machine without Docker.

## API overview

Base path `/api/v1`; interactive docs at `/api/docs`.

| Method & path | Responsibility |
|---|---|
| `POST /api/v1/heat-jobs` | Validate + deduplicate an allowed AOI/date request, submit it to FortyGuard. |
| `GET /api/v1/heat-jobs/{job_id}` | Return authoritative local status; refresh provider state when due. |
| `POST /api/v1/scenarios` | Create a scenario from a completed heat job and planner constraints. |
| `GET /api/v1/scenarios/{scenario_id}` | Restore scenario configuration and source status. |
| `POST /api/v1/scenarios/{scenario_id}/runs` | Run the baseline and constrained portfolio optimizer. |
| `GET /api/v1/portfolio-runs/{run_id}` | Selected stops, metrics, score components, and provenance. |
| `GET /api/v1/portfolio-runs/{run_id}/export.csv` | Auditable review packet. |
| `GET /api/v1/source-snapshots` | Permitted source version and freshness metadata. |
| `GET /api/health` | Application + database readiness, without exposing secrets. |

## Data sources & attribution

| Source | Role | Key fields |
|---|---|---|
| **FortyGuard Temperature API** | Hyperlocal heat exposure (essential) | heatmap GeoJSON, `exceedance` hours |
| **City of Phoenix Bus Stops** | Candidate sites | `STOP_ID`, `NBR_SHELTERS`, `RIDERSHIP`, point geometry |
| **CDC/ATSDR SVI (2022, Arizona)** | Social vulnerability | tract `GEOID`, `RPL_THEMES` percentile, geometry |

Each ingestion records retrieval time, source URL, version, and checksum. **All bundled fixtures are synthetic** — shaped like the real datasets, labeled `DEMO_FIXTURE`, and must not be presented as official data. Verify each source's license and attribution terms before publishing any snapshot.

## Deployment

A multi‑stage `Dockerfile` builds the Vite assets and copies them into the FastAPI runtime image, so a single origin serves both `/api/*` and the app shell. Intended target is **Railway**: one public application service plus a separate PostGIS service over private networking, with `FORTYGUARD_API_KEY` and `DATABASE_URL` held only in protected service variables. Migrations and fixture seed run before the server accepts traffic.

Public demo: `https://shadequeue-app-production.up.railway.app`

## Project status

- ✅ End‑to‑end planning loop: heatmap job → CP‑SAT portfolio → audit cards → CSV export.
- ✅ Backend: scoring, CP‑SAT optimizer (deterministic, reproducible), PostGIS spatial joins with GiST indexes, audit/provenance, credit‑protection controls, unit + integration tests.
- ✅ Frontend talks to `/api/v1`. Runtime badges distinguish `LIVE`, `CACHED_LIVE`, and `DEMO_FIXTURE`.
- ✅ Live FortyGuard submit envelope verified (`POST /v1/heatmap` → `data.activity_id`). Fixture mode remains the labeled fallback.
- ⏳ Phoenix and SVI ingestion scripts exist; the public demo still uses labeled synthetic stops/tracts joined to the heat surface.
- ✅ Railway single‑origin deploy: API + SPA.

## What ShadeQueue may and may not claim

**May claim:** it retrieved a FortyGuard heatmap for the tested case; it combined documented source fields into a versioned proxy score; it produced a reproducible portfolio satisfying the displayed constraints; that portfolio covered more of the declared proxy objective than the declared baseline for the tested scenario.

**May not claim (without further evidence):** any reduction in measured temperature, heat illness, or deaths; actual passenger wait‑minutes; official adoption by Phoenix or Valley Metro; production reliability, fairness, or citywide applicability; that the baseline is the city's current allocation method; or that a recommendation is an authorized investment decision.

See [`SHADEQUEUE_TECH_STACK_PLAN.md`](SHADEQUEUE_TECH_STACK_PLAN.md) for the full architecture, delivery phases, and claim boundaries, and [`docs/backend.md`](docs/backend.md) for backend implementation notes.

## License

Released under the [MIT License](LICENSE) © 2026 **sha256** — Bagus Ardin Prayoga and Grady Xiao Yan Lupertama.
