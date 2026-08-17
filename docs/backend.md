# ShadeQueue backend

Implementation notes for `apps/api`. The product rationale and the boundaries on
what ShadeQueue may claim live in `SHADEQUEUE_TECH_STACK_PLAN.md`; this document
records what was actually built, and where reality differed from the plan.

## Layout

```text
apps/api/app/
|- config.py            settings and provider constants
|- runtime.py           event loop selection (see "Windows" below)
|- main.py              app factory, middleware, error mapping
|- static.py            SPA mount with deep-link fallback
|- domain/              pure logic: aoi, scoring, reason_codes, runtime_mode, errors
|- integrations/
|  `- fortyguard/       client, response parsing, fixture provider
|- optimizer/           baseline + CP-SAT model
|- services/            heat_jobs, portfolio, spatial, snapshots, audit, export_csv
|- db/                  models, session, base
`- api/                 schemas, presenters, deps, routes
```

Dependency direction is one-way: `api -> services -> domain`. Nothing in
`domain/` imports SQLAlchemy, FastAPI, or httpx, which is why the scoring and
optimizer tests need no database.

## Running it

```bash
docker compose up -d                                            # PostGIS on 55432
uv sync --project apps/api                                      # Python 3.12 venv
uv run --project apps/api alembic upgrade head                  # schema
uv run --project apps/api python scripts/load_fixtures.py       # demo data
uv run --project apps/api python apps/api/serve.py              # http://127.0.0.1:8000
```

Frontend dev server proxies `/api` to port 8000, so `npm run dev` and the
command above are the two processes for local work.

Tests:

```bash
uv run --project apps/api python -m pytest apps/api/tests
uv run --project apps/api ruff check apps/api scripts migrations
```

Integration tests skip themselves when `DATABASE_URL` is unreachable, so the
unit suite still runs on a machine without Docker.

## FortyGuard contract: what is pinned and what is not

The **request** side is taken from the published OpenAPI document at
<https://api.fortyguard.com/openapi.json>. `HeatmapSubmitRequest` declares:

| Field | Type | Notes |
|---|---|---|
| `polygon_aoi` | object | required |
| `date_time` | `DateTimeRange` | required; `start_date` + `filter_type` required inside |
| `granularity` | int | 60, 80, 100 (default 100) |
| `analytic_type` | string | tcm, time_of_measure, exceedance, persistence |
| `threshold` | number | **degrees Celsius** |
| `direction` | string | above, below |

`filter_type`: 1 = single hour, 2 = range of hours, 3 = single day, 4 = range of days.

**The threshold is Celsius.** The API accepts `thresholdFahrenheit` as a
convenience and converts before hashing, so `40 °C` and `104 °F` resolve to the
same cached job rather than two provider calls.

The **response** side is not pinned. That same document declares the 200
responses of `POST /v1/heatmap` and `GET /v1/status/{activity_id}` as empty
schemas, and defines no `securitySchemes`. Two consequences:

1. `app/integrations/fortyguard/schemas.py` accepts a documented set of aliases
   for the activity id, the status token, and the map data, records which alias
   matched in `parse_notes`, and raises `MalformedProviderResponseError` when
   none match. It never invents a value.
2. The auth header is configurable. Default is `x-api-key`; set
   `FORTYGUARD_API_KEY_HEADER=Authorization` and
   `FORTYGUARD_API_KEY_PREFIX="Bearer "` if the credentials turn out to be
   bearer tokens.

**Before the first live run, verify both against a real response** and tighten
the parser once the real shape is known.

## Runtime modes

`LIVE`, `CACHED_LIVE`, `DEMO_FIXTURE` are derived from stored facts, never from
what the caller asked for:

- `DEMO_FIXTURE` — produced by the fixture provider. Stays a fixture forever.
- `CACHED_LIVE` — a live result being reused (`heat_jobs.reuse_count > 0`).
- `LIVE` — a live result served within its own job lifecycle.

`reuse_count` is an addition to the column list in plan section 8. Without it the
LIVE/CACHED_LIVE distinction would have to be guessed from timestamps.

Live mode requires **both** `LIVE_PROVIDER_ENABLED=true` and a non-empty
`FORTYGUARD_API_KEY`. A misconfigured live deployment falls back to fixtures and
says so in the mode badge rather than returning fixture-shaped success under a
live label.

Fixtures are parsed by the same functions as live responses. A parser regression
breaks the fixture path too, which is the point.

## Credit protection

Ordering matters more than the individual limits. `submit_heat_job` inserts the
job row — claiming `request_hash` through a partial unique index — and commits
*before* contacting the provider. Two racing requests therefore produce one
provider call and one reuse. The index is partial (`WHERE state <> 'FAILED'`) so
a failed job can still be retried.

Other controls: predeclared AOI containment, geodesic area cap, approved date
window, provider enum validation before the network call, per-deployment and
per-client daily live-run caps, request body size cap, explicit connect/read and
end-to-end timeouts.

`ALLOWED_AOI_GEOJSON` lives in `app/domain/aoi.py` rather than in the
environment: widening it widens credit exposure, so the change should be visible
in a diff.

## Scoring and the optimizer

```text
heat_burden_i = normalized_ridership_i * exceedance_hours_i
                * (1 + equity_weight * svi_percentile_i)
```

Normalisation is relative to the candidate set for that scenario, so scores
compare within one run and not across corridors. `final_score` is `raw_burden`
rescaled to 0-100 by one positive constant, so maximising either selects the
same portfolio; the 0-100 form is used because it is what the interface shows.

CP-SAT needs integers, so coefficients are `round(final_score * 10_000)`. The
scale factor, constraints, solver status, solver version, and formula version
are all persisted on the run.

Determinism: one worker, fixed seed, and ties broken on `stop_id` throughout.
The same scenario run twice returns the same portfolio, which is asserted in
`test_the_same_scenario_run_twice_is_reproducible`.

Infeasibility is detected *before* the solver where possible, so the API can say
which constraint failed instead of returning a bare status. An infeasible run is
still a run: it is stored, returns 201, keeps the full candidate list, and still
reports the baseline value.

## Spatial join

`ST_Intersects` against `heat_cells` is primary. Overlapping cells resolve to
`MAX(metric_value)`. A stop that intersects nothing falls back to the nearest
cell within `NEAREST_CELL_MAX_DEGREES` (0.01°, about 1.1 km) and is tagged
`HEAT_VALUE_FROM_NEAREST_CELL`. Beyond that it scores zero and is tagged
`NO_HEAT_COVERAGE`. Exposure is never fabricated.

GiST indexes exist on all three geometry columns and are asserted by
`test_gist_indexes_exist_on_every_geometry_column`.

## Windows: event loops

psycopg's async mode cannot run on `ProactorEventLoop`, which is Windows'
default. Worse, uvicorn 0.36+ calls `asyncio.run(..., loop_factory=...)`, which
bypasses the event loop policy entirely and hard-codes `ProactorEventLoop` on
Windows unless a subprocess is in use — so setting the policy is not enough for
`--reload`-less runs.

Two entry points in `app/runtime.py` cover both paths:

- `configure_event_loop()` — sets the policy, for anything going through
  `asyncio.run` (Alembic, scripts, pytest).
- `new_event_loop()` — a loop factory passed to uvicorn as
  `--loop app.runtime:new_event_loop`.

Both are no-ops on Linux. The Dockerfile passes the factory anyway so the
container and a Windows workstation behave identically.

## Fixtures

`scripts/generate_fixtures.py` regenerates everything in `fixtures/`
deterministically. It asserts that each stop falls inside exactly one heat cell
and exactly one SVI tract, and that no two tracts overlap — otherwise the
expected values in the integration tests would be meaningless.

All fixture values are synthetic. They are shaped like the real datasets and are
labelled `DEMO_FIXTURE` in `source_snapshots`; they are not derived from any
official source and must not be presented as one.

## Not yet done

- No live FortyGuard call has been made. The adapter is untested against the
  real service, and the response parser is provisional (see above).
- `scripts/ingest_phoenix.py` and `scripts/ingest_svi.py` are written but have
  not been run against the live sources. Run them with `--dry-run` first and
  read the null/range report before writing.
- `RIDERSHIP` period and unit are still unverified, so the UI must keep calling
  it a source-provided value.
- No Railway deployment. The Dockerfile builds the intended image but has not
  been deployed.
- No Playwright end-to-end coverage; that lives with the frontend.
