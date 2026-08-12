import { useMemo, useState } from 'react'
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileCheck2,
  Info,
  Scale,
  ShieldAlert,
  SlidersHorizontal,
} from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { createScenarioFixture, type Stop } from '../data/fixture'
import { formatDateTime, formatNumber } from '../lib/utils'

function finiteParam(value: string | null, fallback: number) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function escapeCsv(value: string | number | null) {
  const normalized = value === null ? '' : String(value)
  return `"${normalized.replaceAll('"', '""')}"`
}

function selectedReason(stop: Stop) {
  if (stop.reasonCodes.includes('HIGH_HEAT_EXPOSURE')) return 'Heat-led priority'
  if (stop.reasonCodes.includes('HIGH_SOURCE_RIDERSHIP')) return 'Demand-led priority'
  if (stop.reasonCodes.includes('HIGH_SOCIAL_VULNERABILITY')) return 'Equity-led priority'
  return 'Balanced portfolio value'
}

export function PortfolioPage() {
  const { runId = 'portfolio-fixture-001' } = useParams()
  const [searchParams] = useSearchParams()
  const [exportStatus, setExportStatus] = useState('')
  const data = useMemo(
    () =>
      createScenarioFixture({
        shelterSlots: finiteParam(searchParams.get('slots'), 10),
        equityWeight: finiteParam(searchParams.get('equity'), 0.45),
        minimumEquityShare: finiteParam(searchParams.get('share'), 0.4),
      }),
    [searchParams],
  )
  const selectedStops = data.stops.filter((stop) => stop.selected).sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
  const baselineStops = data.stops.filter((stop) => stop.baselineSelected)
  const baselineOnly = baselineStops.filter((stop) => !stop.selected)
  const optimizedOnly = selectedStops.filter((stop) => !stop.baselineSelected)
  const overlapCount = selectedStops.filter((stop) => stop.baselineSelected).length
  const gain = ((data.objectiveValue - data.baselineValue) / data.baselineValue) * 100
  const highEquityCount = selectedStops.filter((stop) => stop.sviPercentile >= 0.75).length
  const scenarioQuery = searchParams.toString()

  const handleExport = () => {
    try {
      const headings = [
        'rank',
        'stop_id',
        'stop_name',
        'fixture_mode',
        'heat_exceedance_hours',
        'source_ridership_value',
        'svi_percentile',
        'final_score',
        'formula_version',
        'reason_codes',
      ]
      const rows = selectedStops.map((stop) => [
        stop.rank,
        stop.stopId,
        stop.name,
        data.runtimeMode,
        stop.exceedanceHours,
        stop.ridershipValue,
        stop.sviPercentile,
        stop.finalScore.toFixed(2),
        data.formulaVersion,
        stop.reasonCodes.join('|'),
      ])
      const csv = [headings, ...rows].map((row) => row.map(escapeCsv).join(',')).join('\r\n')
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `shadequeue-${runId}-fixture.csv`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      setExportStatus('Fixture review CSV downloaded successfully.')
    } catch {
      setExportStatus('Export failed. No file was downloaded; try again.')
    }
  }

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-7 sm:px-6 sm:py-9 lg:px-8">
      <Link
        to={`/scenarios/${data.scenarioId}${scenarioQuery ? `?${scenarioQuery}` : ''}`}
        className="app-link inline-flex min-h-10 items-center gap-2 text-sm"
      >
        <ArrowLeft className="size-4" aria-hidden="true" /> Back to corridor review
      </Link>

      <header className="mt-5 grid gap-6 border-b border-line pb-7 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="fixture">Demo fixture</Badge>
            <Badge tone="success">Contract status: {data.solverStatus}</Badge>
          </div>
          <h1 className="mt-4 max-w-4xl text-[clamp(2.6rem,6vw,5.4rem)] font-black leading-[0.92] tracking-[-0.072em]">
            {selectedStops.length} allocations. <span className="text-heat">Every one auditable.</span>
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-muted-ink">
            Compare the ridership-only proxy baseline with the constraint-aware fixture portfolio, then export a review packet for human deliberation.
          </p>
        </div>
        <div className="lg:text-right">
          <Button onClick={handleExport} className="w-full sm:w-auto">
            <Download className="size-4" aria-hidden="true" /> Download review CSV
          </Button>
          <p className="mt-2 text-xs text-muted-ink">Exports fixture data only</p>
        </div>
      </header>

      {exportStatus ? (
        <div
          role="status"
          className={`mt-5 flex items-start gap-3 border p-3 text-sm font-semibold ${exportStatus.startsWith('Export failed') ? 'border-danger/30 bg-[#fff0e9] text-[#842c21]' : 'border-action/25 bg-[#e6f3ef] text-action-strong'}`}
        >
          {exportStatus.startsWith('Export failed') ? <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> : <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
          {exportStatus}
        </div>
      ) : null}

      <section className="mt-6 grid gap-px border border-line bg-line lg:grid-cols-[1fr_1fr_0.78fr]" aria-label="Portfolio comparison summary">
        <article className="bg-panel p-5 sm:p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.13em] text-muted-ink">Baseline proxy</p>
              <h2 className="mt-1 text-xl font-extrabold">Highest source values</h2>
            </div>
            <Scale className="size-5 text-muted-ink" aria-hidden="true" />
          </div>
          <p className="metric-numeral mt-7 text-4xl font-bold">{data.baselineValue.toFixed(1)}</p>
          <div className="mt-3 h-2 bg-[#e3e0d6]" aria-hidden="true">
            <div className="h-full bg-[#77857f]" style={{ width: `${(data.baselineValue / data.objectiveValue) * 100}%` }} />
          </div>
          <p className="mt-3 text-xs leading-5 text-muted-ink">Not Phoenix's official planning process. Used only as a declared comparison.</p>
        </article>

        <article className="bg-[#eaf4f1] p-5 sm:p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.13em] text-action">Fixture portfolio</p>
              <h2 className="mt-1 text-xl font-extrabold">Heat + demand + equity</h2>
            </div>
            <FileCheck2 className="size-5 text-action" aria-hidden="true" />
          </div>
          <div className="mt-7 flex items-end gap-3">
            <p className="metric-numeral text-4xl font-bold">{data.objectiveValue.toFixed(1)}</p>
            <Badge tone="success" className="mb-1">+{gain.toFixed(1)}%</Badge>
          </div>
          <div className="mt-3 h-2 bg-[#cbded8]" aria-hidden="true"><div className="h-full w-full bg-action" /></div>
          <p className="mt-3 text-xs leading-5 text-muted-ink">Objective coverage for this deterministic UI fixture, not measured impact.</p>
        </article>

        <article className="bg-panel p-5 sm:p-6">
          <p className="text-xs font-bold uppercase tracking-[0.13em] text-muted-ink">Portfolio delta</p>
          <dl className="mt-5 space-y-4 text-sm">
            <div className="flex items-baseline justify-between gap-4"><dt className="text-muted-ink">Shared stops</dt><dd className="metric-numeral text-xl font-bold">{overlapCount}</dd></div>
            <div className="flex items-baseline justify-between gap-4"><dt className="text-muted-ink">Swapped in</dt><dd className="metric-numeral text-xl font-bold">{optimizedOnly.length}</dd></div>
            <div className="flex items-baseline justify-between gap-4"><dt className="text-muted-ink">High-SVI selected</dt><dd className="metric-numeral text-xl font-bold">{highEquityCount}</dd></div>
          </dl>
        </article>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(22rem,0.85fr)]">
        <section className="border border-line bg-panel" aria-labelledby="selected-stops-title">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line p-5">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.13em] text-heat">Recommended review set</p>
              <h2 id="selected-stops-title" className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">Selected stops</h2>
            </div>
            <p className="text-xs text-muted-ink">Sorted by fixture portfolio rank</p>
          </div>
          <ol className="divide-y divide-line">
            {selectedStops.map((stop) => (
              <li key={stop.stopId} className="grid gap-4 p-4 sm:grid-cols-[2.5rem_minmax(0,1fr)_auto] sm:items-center sm:px-5">
                <span className="metric-numeral grid size-10 place-items-center border border-ink bg-ink text-sm font-bold text-panel">{String(stop.rank).padStart(2, '0')}</span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-bold">{stop.name}</h3>
                    {!stop.baselineSelected ? <Badge tone="heat">Swapped in</Badge> : null}
                  </div>
                  <p className="mt-1 text-xs text-muted-ink">{selectedReason(stop)} · {stop.exceedanceHours.toFixed(1)} exceedance h · {Math.round(stop.sviPercentile * 100)}th SVI percentile</p>
                </div>
                <div className="sm:text-right">
                  <p className="metric-numeral text-xl font-bold">{stop.finalScore.toFixed(1)}</p>
                  <p className="text-[0.65rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Proxy score</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <aside className="space-y-5">
          <section className="border border-ink bg-panel" aria-labelledby="constraint-title">
            <div className="thermal-rule" />
            <div className="p-5">
              <div className="flex items-center gap-3">
                <SlidersHorizontal className="size-5 text-action" aria-hidden="true" />
                <h2 id="constraint-title" className="text-lg font-extrabold">Constraint ledger</h2>
              </div>
              <dl className="mt-5 space-y-4 text-sm">
                {[
                  ['Shelter slots', String(data.shelterSlots)],
                  ['Existing shelters', 'Excluded'],
                  ['Equity weight', `${Math.round(data.equityWeight * 100)}%`],
                  ['Minimum high-SVI share', `${Math.round(data.minimumEquityShare * 100)}%`],
                  ['Fixture solver state', data.solverStatus],
                  ['Formula', data.formulaVersion],
                ].map(([term, value]) => (
                  <div key={term} className="flex items-start justify-between gap-5 border-b border-line pb-3 last:border-0 last:pb-0">
                    <dt className="text-muted-ink">{term}</dt>
                    <dd className="max-w-[12rem] text-right font-mono text-xs font-bold">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>

          <section className="border border-[#8d4f09]/30 bg-[#fff6df] p-5" aria-labelledby="authority-title">
            <Info className="size-5 text-[#825b08]" aria-hidden="true" />
            <h2 id="authority-title" className="mt-4 text-lg font-extrabold">Human decision required</h2>
            <p className="mt-2 text-sm leading-6 text-[#66420d]">This portfolio is a candidate review packet. It does not perform procurement, publish a city decision, or update a transit system.</p>
          </section>

          {baselineOnly.length > 0 ? (
            <section className="border border-line bg-panel-raised p-5" aria-labelledby="baseline-only-title">
              <h2 id="baseline-only-title" className="text-sm font-extrabold">Baseline stops not selected</h2>
              <ul className="mt-3 space-y-2 text-xs text-muted-ink">
                {baselineOnly.map((stop) => (
                  <li key={stop.stopId} className="flex items-center justify-between gap-3">
                    <span>{stop.name}</span>
                    <span className="metric-numeral font-bold text-ink">{formatNumber(stop.ridershipValue)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>

      <section className="mt-6 border border-line bg-panel p-5" aria-labelledby="audit-stamp-title">
        <div className="grid gap-5 md:grid-cols-[auto_1fr_auto] md:items-center">
          <div className="grid size-12 place-items-center border border-action bg-[#eaf4f1] text-action"><FileCheck2 aria-hidden="true" /></div>
          <div>
            <h2 id="audit-stamp-title" className="font-extrabold">Fixture audit stamp</h2>
            <p className="mt-1 text-xs leading-5 text-muted-ink">Created {formatDateTime(data.completedAt)} MST · runtime {data.runtimeMode} · no live provider activity ID · no backend persistence</p>
          </div>
          <span className="font-mono text-xs font-bold text-muted-ink">{runId}</span>
        </div>
      </section>
    </div>
  )
}
