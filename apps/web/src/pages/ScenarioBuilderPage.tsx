import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  CheckCircle2,
  DatabaseZap,
  FileSearch,
  MapPinned,
  ShieldCheck,
  SlidersHorizontal,
  ThermometerSun,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import {
  ApiError,
  createHeatJob,
  createRun,
  createScenario,
  getSourceSnapshots,
  modeLabel,
  rememberSession,
  waitForHeatJob,
  type HeatJob,
  type SourceBootstrap,
} from '../lib/api'

const flowSteps = [
  { icon: MapPinned, label: 'Scope', detail: 'One approved Phoenix corridor' },
  { icon: ThermometerSun, label: 'Exposure', detail: 'FortyGuard exceedance hours' },
  { icon: SlidersHorizontal, label: 'Allocate', detail: 'Slots + transparent equity rule' },
  { icon: FileSearch, label: 'Review', detail: 'Map, table, and stop-level audit' },
]

export function ScenarioBuilderPage() {
  const navigate = useNavigate()
  const [shelterSlots, setShelterSlots] = useState(10)
  const [equityWeight, setEquityWeight] = useState(45)
  const [minimumEquityShare, setMinimumEquityShare] = useState(40)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [phase, setPhase] = useState('')
  const [startDate, setStartDate] = useState('2024-07-01')
  const [endDate, setEndDate] = useState('2024-07-31')
  const [bootstrap, setBootstrap] = useState<SourceBootstrap | null>(null)
  const [jobPreview, setJobPreview] = useState<HeatJob | null>(null)

  useEffect(() => {
    let cancelled = false
    getSourceSnapshots()
      .then((value) => {
        if (cancelled) return
        setBootstrap(value)
        setStartDate((current) => (current < value.allowedDateMin ? value.allowedDateMin : current))
      })
      .catch(() => {
        if (!cancelled) setBootstrap(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setPhase('')
    setJobPreview(null)
    if (!bootstrap) {
      setError('The planning API is not reachable yet. Confirm the backend is up, then retry.')
      return
    }
    setSubmitting(true)
    try {
      setPhase('Submitting heatmap job to FortyGuard…')
      const job = await createHeatJob({
        aoi: bootstrap.allowedAoi,
        startDate,
        endDate,
        filterType: 4,
        thresholdFahrenheit: 104,
        analyticType: 'exceedance',
      })
      setJobPreview(job)
      setPhase(
        job.runtimeMode === 'DEMO_FIXTURE'
          ? 'Waiting on the deterministic heat surface…'
          : 'Polling FortyGuard until the heat surface is ready…',
      )
      const completed = await waitForHeatJob(job.jobId, setJobPreview)
      setPhase('Solving the constrained shelter portfolio with CP-SAT…')
      const scenario = await createScenario({
        heatJobId: completed.jobId,
        name: 'Central Phoenix heat scenario',
        shelterSlots,
        equityWeight: equityWeight / 100,
        minimumEquityShare: minimumEquityShare / 100,
      })
      const run = await createRun(scenario.scenarioId)
      rememberSession(scenario.scenarioId, run.runId)
      navigate(`/scenarios/${scenario.scenarioId}?run=${run.runId}`)
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : 'The scenario could not be built.'
      setError(message)
      setPhase('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <section className="relative overflow-hidden border-b border-line bg-panel">


        <div className="relative mx-auto grid max-w-[100rem] gap-8 px-4 py-10 sm:px-6 sm:py-14 lg:grid-cols-[minmax(0,1.05fr)_minmax(28rem,0.95fr)] lg:items-start lg:px-8 lg:py-16">
          <div className="max-w-2xl pt-1 lg:pt-4">
            <p className="mb-4 text-xs font-bold uppercase tracking-[0.15em] text-heat">
              Guided demo · 01 <span className="mx-2 text-line">|</span>{' '}
              <span className="text-muted-ink">
                {bootstrap?.liveProviderEnabled ? 'Live FortyGuard heatmap' : 'Fixture heat surface · live switch off'}
              </span>
            </p>
            <h1 className="mt-2 max-w-2xl text-[clamp(2.7rem,7vw,5.8rem)] font-black leading-[0.92] tracking-[-0.09em]">
              Put limited shade where <span className="text-heat">heat burden</span> converges.
            </h1>
            <p className="mt-6 max-w-xl text-base leading-7 text-muted-ink sm:text-lg">
              Configure a transparent shelter-allocation preview for one Phoenix corridor, then inspect every selected stop on the map and in an equivalent table.
            </p>

            <ol className="mt-8 grid gap-px border border-line bg-line sm:grid-cols-2">
              {flowSteps.map(({ icon: Icon, label, detail }, index) => (
                <li key={label} className="bg-panel p-4">
                  <div className="flex gap-3">
                    <span className="metric-numeral text-xs font-bold text-heat">0{index + 1}</span>
                    <Icon className="size-5 shrink-0 text-action" strokeWidth={1.9} aria-hidden="true" />
                    <span>
                      <strong className="block text-sm">{label}</strong>
                      <span className="mt-0.5 block text-xs leading-5 text-muted-ink">{detail}</span>
                    </span>
                  </div>
                </li>
              ))}
            </ol>

            <div className="mt-6 flex gap-3 border-l-2 border-sun pl-4 text-sm leading-6 text-muted-ink">
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-[#8d6509]" aria-hidden="true" />
              <p><strong className="text-ink">Human authority stays visible.</strong> This interface ranks review candidates; it does not authorize construction or claim health outcomes.</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="border border-ink bg-panel shadow-[8px_8px_0_#142925]" aria-labelledby="scenario-form-title">
            <div className="thermal-rule" />
            <div className="border-b border-line p-5 sm:p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.14em] text-heat">Scenario contract</p>
                  <h2 id="scenario-form-title" className="mt-1 text-2xl font-extrabold tracking-[-0.04em]">Configure the preview</h2>
                </div>
                <DatabaseZap className="size-6 text-action" aria-hidden="true" />
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-ink">
                {bootstrap
                  ? `Corridor locked to ${bootstrap.allowedAoiName}. Heat comes from the Temperature API when live mode is on.`
                  : 'Waiting for the planning API. The form stays disabled until source snapshots load.'}
              </p>
            </div>

            <div className="space-y-5 p-5 sm:p-6">
              {error ? (
                <div role="alert" className="border border-danger/35 bg-[#fff0e9] p-3 text-sm font-semibold text-[#842c21]">
                  {error}
                </div>
              ) : null}

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="sm:col-span-2">
                  <span className="mb-1.5 block text-sm font-bold">Area of interest</span>
                  <select className="field-control" defaultValue="central-phoenix">
                    <option value="central-phoenix">Central / 7th Avenue corridor · Phoenix</option>
                  </select>
                  <span className="mt-1.5 block text-xs text-muted-ink">
                    Predeclared Phoenix envelope · max {bootstrap?.maxAoiAreaKm2 ?? 25} km².
                  </span>
                </label>

                <label>
                  <span className="mb-1.5 block text-sm font-bold">Heat window start</span>
                  <input
                    className="field-control"
                    type="date"
                    min={bootstrap?.allowedDateMin ?? '2024-06-01'}
                    max={bootstrap?.allowedDateMax ?? '2026-08-31'}
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                  />
                </label>
                <label>
                  <span className="mb-1.5 block text-sm font-bold">Heat window end</span>
                  <input
                    className="field-control"
                    type="date"
                    min={bootstrap?.allowedDateMin ?? '2024-06-01'}
                    max={bootstrap?.allowedDateMax ?? '2026-08-31'}
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                  />
                </label>

                <label>
                  <span className="mb-1.5 block text-sm font-bold">Analytic metric</span>
                  <select className="field-control" defaultValue="exceedance">
                    <option value="exceedance">Exceedance hours</option>
                  </select>
                </label>

                <label>
                  <span className="mb-1.5 flex items-center justify-between gap-3 text-sm font-bold">
                    Shelter slots <output className="metric-numeral text-action">{shelterSlots}</output>
                  </span>
                  <input
                    className="min-h-11 w-full cursor-pointer"
                    type="range"
                    aria-label="Shelter slots"
                    min="5"
                    max="12"
                    step="1"
                    value={shelterSlots}
                    onChange={(event) => setShelterSlots(Number(event.target.value))}
                  />
                  <span className="mt-1 block text-xs text-muted-ink">Fixed-count allocation; no cost claim.</span>
                </label>

                <label>
                  <span className="mb-1.5 block text-sm font-bold">Comparison threshold</span>
                  <span className="relative block">
                    <input className="field-control pr-12" type="number" value="104" readOnly />
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm font-bold text-muted-ink">°F</span>
                  </span>
                  <span className="mt-1.5 block text-xs text-muted-ink">Analysis parameter, not a safety threshold.</span>
                </label>
              </div>

              <fieldset className="border-t border-line pt-5">
                <legend className="px-2 text-sm font-extrabold">Equity constraint</legend>
                <div className="mt-2 grid gap-5 sm:grid-cols-2">
                  <label>
                    <span className="mb-1.5 flex items-center justify-between gap-3 text-sm font-bold">
                      SVI weight <output className="metric-numeral text-action">{equityWeight}%</output>
                    </span>
                    <input
                      className="min-h-11 w-full cursor-pointer"
                      type="range"
                      aria-label="SVI weight"
                      min="0"
                      max="80"
                      step="5"
                      value={equityWeight}
                      onChange={(event) => setEquityWeight(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    <span className="mb-1.5 flex items-center justify-between gap-3 text-sm font-bold">
                      Minimum high-SVI share <output className="metric-numeral text-action">{minimumEquityShare}%</output>
                    </span>
                    <input
                      className="min-h-11 w-full cursor-pointer"
                      type="range"
                      aria-label="Minimum high-SVI share"
                      min="0"
                      max="60"
                      step="10"
                      value={minimumEquityShare}
                      onChange={(event) => setMinimumEquityShare(Number(event.target.value))}
                    />
                  </label>
                </div>
              </fieldset>

              <div className="border border-[#8d4f09]/25 bg-[#fff6df] p-3 text-xs leading-5 text-[#66420d]">
                {bootstrap?.liveProviderEnabled ? (
                  <>
                    <strong>Live mode:</strong> this run spends a FortyGuard heatmap credit, then CP-SAT
                    selects the shelter portfolio. The runtime badge never labels a fixture as live.
                  </>
                ) : (
                  <>
                    <strong>Fixture mode:</strong> the same submit-and-poll contract runs against a
                    deterministic heat surface. Enable live mode on the server to spend API credit.
                  </>
                )}
              </div>

              {jobPreview ? (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={jobPreview.runtimeMode === 'DEMO_FIXTURE' ? 'fixture' : 'success'}>
                    {modeLabel(jobPreview.runtimeMode)}
                  </Badge>
                  <span className="font-mono text-muted-ink">{jobPreview.state}</span>
                  {jobPreview.providerActivityId ? (
                    <span className="font-mono text-muted-ink">activity {jobPreview.providerActivityId.slice(0, 8)}</span>
                  ) : null}
                </div>
              ) : null}

              <Button type="submit" className="w-full" disabled={submitting || !bootstrap} aria-busy={submitting}>
                {submitting ? phase || 'Working…' : 'Build heat-aware portfolio'}
                {!submitting ? <ArrowRight className="size-4" aria-hidden="true" /> : null}
              </Button>
              <p className="text-center text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-muted-ink" aria-live="polite">
                {submitting
                  ? phase
                  : bootstrap?.liveProviderEnabled
                    ? 'Live heatmap · CP-SAT solver · human review only'
                    : 'Fixture heatmap · CP-SAT solver · human review only'}
              </p>
            </div>
          </form>
        </div>
      </section>

      <section id="methodology" className="mx-auto max-w-[100rem] px-4 py-12 sm:px-6 lg:px-8" aria-labelledby="method-title">
        <div className="grid gap-8 lg:grid-cols-[0.75fr_1.25fr]">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.15em] text-heat">Method boundary</p>
            <h2 id="method-title" className="mt-2 text-3xl font-extrabold tracking-[-0.045em]">A decision aid with receipts.</h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-muted-ink">The frontend keeps the planning assumptions beside the recommendation so a reviewer can question the score instead of trusting a black box.</p>
          </div>
          <div className="grid gap-px border border-line bg-line sm:grid-cols-3">
            {[
              ['01', 'Observe', 'Heat exceedance, source-provided ridership, and SVI remain visible as separate inputs.'],
              ['02', 'Constrain', 'Existing shelters are excluded; slot count and minimum equity share are explicit.'],
              ['03', 'Audit', 'Every candidate exposes raw values, normalized components, formula version, and reason codes.'],
            ].map(([number, title, copy]) => (
              <article key={number} className="bg-panel p-5">
                <span className="metric-numeral text-sm font-bold text-heat">{number}</span>
                <h3 className="mt-6 text-lg font-extrabold">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-ink">{copy}</p>
                <CheckCircle2 className="mt-5 size-4 text-action" aria-hidden="true" />
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
