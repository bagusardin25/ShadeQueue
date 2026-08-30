import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Clock3, Database, Edit3, MapPinned, RefreshCcw, TriangleAlert } from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { CorridorMap } from '../components/CorridorMap'
import { RunInsights } from '../components/RunInsights'
import { StopAuditPanel } from '../components/StopAuditPanel'
import { StopsTable } from '../components/StopsTable'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { formatDateTime } from '../lib/utils'
import { isUuid, loadFixtureView, loadLiveScenario, modeLabel } from '../lib/api'
import { existingShelterCount, objectiveDelta, portfolioRankById } from '../lib/planning'

function asFiniteNumber(value: string | null, fallback: number) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function ScenarioLoading() {
  return (
    <div className="mx-auto max-w-[100rem] px-4 py-8 sm:px-6 lg:px-8" aria-busy="true" aria-label="Loading corridor scenario">
      <div className="skeleton h-5 w-44" />
      <div className="skeleton mt-5 h-12 max-w-2xl" />
      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((item) => <div key={item} className="skeleton h-28" />)}
      </div>
      <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(28rem,0.85fr)]">
        <div className="skeleton min-h-[31rem]" />
        <div className="skeleton min-h-[31rem]" />
      </div>
    </div>
  )
}

export function ScenarioPage() {
  const { scenarioId = 'phoenix-central-fixture' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null)
  const fixtureOptions = useMemo(
    () => ({
      state: searchParams.get('state') ?? undefined,
      shelterSlots: asFiniteNumber(searchParams.get('slots'), 10),
      equityWeight: asFiniteNumber(searchParams.get('equity'), 0.45),
      minimumEquityShare: asFiniteNumber(searchParams.get('share'), 0.4),
    }),
    [searchParams],
  )
  const query = useQuery({
    queryKey: ['scenario', scenarioId, searchParams.get('run'), fixtureOptions],
    queryFn: async () => {
      if (isUuid(scenarioId)) {
        return loadLiveScenario(scenarioId, searchParams.get('run') ?? undefined)
      }
      return loadFixtureView(fixtureOptions)
    },
  })

  if (query.isPending) return <ScenarioLoading />

  if (query.isError) {
    const useSafeFixture = () => {
      const next = new URLSearchParams(searchParams)
      next.delete('state')
      setSearchParams(next)
    }
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <section className="border border-danger/50 bg-panel" aria-labelledby="provider-error-title">
          <div className="thermal-rule bg-danger" />
          <div className="p-6 sm:p-8">
            <TriangleAlert className="size-7 text-danger" aria-hidden="true" />
            <Badge tone="warning" className="mt-5">Provider timeout preview</Badge>
            <h1 id="provider-error-title" className="mt-3 text-3xl font-extrabold tracking-[-0.045em]">The heat status check did not complete.</h1>
            <p className="mt-3 max-w-xl leading-7 text-muted-ink">No portfolio was presented as live success. Your scenario inputs remain intact; continue with the explicit deterministic fixture or return to configuration.</p>
            <p className="mt-4 border-l-2 border-danger pl-3 text-sm font-semibold text-[#7b2d24]">{query.error.message}</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/scenarios/new" className="inline-flex min-h-11 items-center rounded-md bg-action px-4 text-sm font-bold text-white hover:bg-action-strong focus-visible:outline-2 focus-visible:outline-focus">Edit scenario</Link>
              {!isUuid(scenarioId) ? (
                <Button onClick={useSafeFixture}><RefreshCcw className="size-4" aria-hidden="true" /> Use safe fixture</Button>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    )
  }

  const data = query.data
  if (data.stops.length === 0) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <section className="border border-line bg-panel p-6 sm:p-8" aria-labelledby="empty-title">
          <MapPinned className="size-7 text-muted-ink" aria-hidden="true" />
          <Badge tone="neutral" className="mt-5">Empty corridor</Badge>
          <h1 id="empty-title" className="mt-3 text-3xl font-extrabold tracking-[-0.045em]">No active stops intersect this AOI.</h1>
          <p className="mt-3 leading-7 text-muted-ink">The optimizer was not run. Adjust the area of interest and validate it again.</p>
          <Link to="/scenarios/new" className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-md bg-action px-4 text-sm font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
            <Edit3 className="size-4" aria-hidden="true" /> Edit corridor
          </Link>
        </section>
      </div>
    )
  }

  const selectedCount = data.stops.filter((stop) => stop.selected).length
  const eligibleCount = data.stops.filter((stop) => stop.shelterCount === 0).length
  const recordedShelters = existingShelterCount(data.stops)
  const currentStopId = selectedStopId ?? data.stops.find((stop) => stop.selected)?.stopId ?? data.stops[0]!.stopId
  const selectedStop = data.stops.find((stop) => stop.stopId === currentStopId) ?? data.stops[0]!
  const delta = objectiveDelta(data.objectiveValue, data.baselineValue)
  const pinRanks = portfolioRankById(data.stops)
  const highEquityShare =
    selectedCount === 0
      ? 0
      : data.stops.filter((stop) => stop.selected && stop.sviPercentile >= 0.75).length / selectedCount
  const portfolioSearch = searchParams.toString()

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-7 sm:px-6 sm:py-9 lg:px-8">
      <div className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.11em] text-muted-ink">
        <Link to="/scenarios/new" className="inline-flex min-h-10 items-center hover:text-ink hover:underline">Scenarios</Link>
        <span aria-hidden="true">/</span>
        <span>{data.corridorName}</span>
      </div>

      <header className="mt-5 flex flex-col gap-5 border-b border-line pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="mb-3 flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.15em] text-action">
            {modeLabel(data.runtimeMode)} <span className="text-line">|</span> {data.solverStatus}
          </p>
          <h1 className="text-[clamp(1.85rem,4vw,3.4rem)] font-black leading-none tracking-[-0.07em]">Central / 7th Avenue</h1>
          <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-ink">
            <span className="inline-flex items-center gap-1.5"><Clock3 className="size-4" aria-hidden="true" /> Completed {formatDateTime(data.completedAt)} MST</span>
            <span className="inline-flex items-center gap-1.5"><Database className="size-4" aria-hidden="true" /> {data.heatCellCount ? `${data.heatCellCount} heat cells` : data.formulaVersion}</span>
            {data.providerActivityId ? (
              <span className="inline-flex items-center gap-1.5 font-mono">FortyGuard {data.providerActivityId.slice(0, 8)}</span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/scenarios/new" className="inline-flex min-h-11 items-center gap-2 rounded-md border border-line bg-panel px-4 text-sm font-bold hover:bg-panel-raised focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
            <Edit3 className="size-4" aria-hidden="true" /> Edit scenario
          </Link>
          <Link to={`/portfolios/${data.portfolioId}${portfolioSearch ? `?${portfolioSearch}` : ''}`} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-action bg-action px-4 text-sm font-bold text-white shadow-[0_2px_0_#063f3a] hover:bg-action-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
            Review portfolio <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </div>
      </header>

      <section className="mt-6 grid gap-px border border-line bg-line sm:grid-cols-2 xl:grid-cols-4" aria-label="Scenario summary">
        {[
          ['Allocated', `${selectedCount} / ${eligibleCount}`, `${data.stops.length} official stops · ${recordedShelters} GIS-recorded shelter${recordedShelters === 1 ? '' : 's'} excluded`],
          [
            'Proxy objective',
            data.objectiveValue.toFixed(1),
            delta.kind === 'equity-cost'
              ? `${delta.pct.toFixed(1)}% vs ridership baseline (equity cost)`
              : `${delta.pct >= 0 ? '+' : ''}${delta.pct.toFixed(1)}% vs ridership baseline`,
          ],
          ['High-SVI share', `${Math.round(highEquityShare * 100)}%`, `Constraint ≥ ${Math.round(data.minimumEquityShare * 100)}%`],
          ['Solver', data.solverStatus, data.formulaVersion],
        ].map(([label, value, detail]) => (
          <article key={label} className="bg-panel p-4 sm:p-5">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.12em] text-muted-ink">{label}</p>
            <p className="metric-numeral mt-2 text-2xl font-bold tracking-[-0.04em]">{value}</p>
            <p className="mt-1 text-xs leading-5 text-muted-ink">{detail}</p>
          </article>
        ))}
      </section>

      <RunInsights data={data} />

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.12fr)_minmax(30rem,0.88fr)]">
        <CorridorMap
          stops={data.stops}
          selectedStopId={currentStopId}
          onSelect={setSelectedStopId}
          heatmap={data.heatmap}
          runtimeMode={data.runtimeMode}
        />
        <StopsTable stops={data.stops} selectedStopId={currentStopId} onSelect={setSelectedStopId} />
      </div>

      <div className="mt-5">
        <StopAuditPanel
          stop={selectedStop}
          runtimeMode={data.runtimeMode}
          displayRank={pinRanks.get(selectedStop.stopId)}
        />
      </div>

      <section className="mt-5 border border-line bg-panel-raised" aria-labelledby="sources-title">
        <details className="group" open={data.runtimeMode !== 'DEMO_FIXTURE'}>
          <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus sm:px-5">
            <span id="sources-title">Source versions and evidence</span>
            <span className="text-xs font-bold uppercase tracking-[0.1em] text-muted-ink group-open:hidden">Expand</span>
            <span className="hidden text-xs font-bold uppercase tracking-[0.1em] text-muted-ink group-open:inline">Collapse</span>
          </summary>
          <div className="grid gap-px border-t border-line bg-line md:grid-cols-3">
            {data.sourceVersions.map((source) => (
              <article key={source.name} className="bg-panel p-4">
                <h3 className="text-sm font-bold">{source.name}</h3>
                <p className="mt-2 font-mono text-xs text-heat">{source.version}</p>
                <p className="mt-2 text-xs leading-5 text-muted-ink">{source.evidence}</p>
              </article>
            ))}
          </div>
        </details>
      </section>
    </div>
  )
}
