import { z } from 'zod'
import { createScenarioFixture, type ScenarioFixture, type Stop } from '../data/fixture'

const LAST_SESSION_KEY = 'shadequeue.lastSession'

export class ApiError extends Error {
  readonly code: string
  readonly correlationId?: string

  constructor(code: string, message: string, correlationId?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.correlationId = correlationId
  }
}

export const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function isUuid(value: string) {
  return UUID_RE.test(value)
}

export function rememberSession(scenarioId: string, runId: string) {
  sessionStorage.setItem(LAST_SESSION_KEY, JSON.stringify({ scenarioId, runId }))
}

export function readSession(): { scenarioId: string; runId: string } | null {
  try {
    const raw = sessionStorage.getItem(LAST_SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { scenarioId?: string; runId?: string }
    if (parsed.scenarioId && parsed.runId) return { scenarioId: parsed.scenarioId, runId: parsed.runId }
  } catch {
    return null
  }
  return null
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { message: text }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      accept: 'application/json',
      ...(init?.body ? { 'content-type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  const payload = await parseBody(response)
  if (!response.ok) {
    const record = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {}
    throw new ApiError(
      typeof record.code === 'string' ? record.code : 'HTTP_ERROR',
      typeof record.message === 'string' ? record.message : `Request failed (${response.status})`,
      typeof record.correlationId === 'string' ? record.correlationId : undefined,
    )
  }
  return payload as T
}

const healthSchema = z.object({
  status: z.string(),
  appEnv: z.string(),
  database: z.string(),
  providerConfigured: z.boolean(),
  liveProviderEnabled: z.boolean(),
  version: z.string(),
})

const snapshotSchema = z.object({
  snapshots: z.array(
    z.object({
      id: z.string(),
      sourceName: z.string(),
      sourceUrl: z.string(),
      sourceVersion: z.string(),
      retrievedAt: z.string(),
      checksum: z.string(),
      evidenceMode: z.string(),
      licenseNote: z.string().nullable().optional(),
    }),
  ),
  liveProviderEnabled: z.boolean(),
  allowedAoi: z.record(z.string(), z.unknown()),
  allowedAoiName: z.string(),
  allowedDateMin: z.string(),
  allowedDateMax: z.string(),
  maxAoiAreaKm2: z.number(),
  mapStyleUrl: z.string(),
})

const heatJobSchema = z.object({
  jobId: z.string(),
  state: z.string(),
  runtimeMode: z.enum(['LIVE', 'CACHED_LIVE', 'DEMO_FIXTURE']),
  providerActivityId: z.string().nullable().optional(),
  requestHash: z.string(),
  analyticType: z.string().nullable().optional(),
  thresholdCelsius: z.number().nullable().optional(),
  thresholdFahrenheit: z.number().nullable().optional(),
  heatCellCount: z.number(),
  reused: z.boolean(),
  reuseCount: z.number(),
  createdAt: z.string(),
  completedAt: z.string().nullable().optional(),
  errorCode: z.string().nullable().optional(),
  errorMessage: z.string().nullable().optional(),
  pollRecommended: z.boolean(),
})

const portfolioStopSchema = z.object({
  stopId: z.string(),
  name: z.string(),
  longitude: z.number(),
  latitude: z.number(),
  shelterCount: z.number(),
  ridershipValue: z.number(),
  exceedanceHours: z.number(),
  sviPercentile: z.number(),
  heatComponent: z.number(),
  ridershipComponent: z.number(),
  equityComponent: z.number(),
  finalScore: z.number(),
  selected: z.boolean(),
  baselineSelected: z.boolean(),
  eligible: z.boolean(),
  rank: z.number().nullable(),
  heatJoinMethod: z.string(),
  reasonCodes: z.array(z.string()),
})

const portfolioRunSchema = z.object({
  runId: z.string(),
  scenarioId: z.string(),
  scenarioName: z.string(),
  state: z.string(),
  runtimeMode: z.enum(['LIVE', 'CACHED_LIVE', 'DEMO_FIXTURE']),
  solverStatus: z.string().nullable().optional(),
  solverVersion: z.string().nullable().optional(),
  formulaVersion: z.string(),
  objectiveValue: z.number().nullable().optional(),
  baselineValue: z.number().nullable().optional(),
  shelterSlots: z.number(),
  equityWeight: z.number(),
  minimumEquityShare: z.number(),
  thresholdCelsius: z.number().nullable().optional(),
  thresholdFahrenheit: z.number().nullable().optional(),
  metricName: z.string(),
  infeasibleReason: z.string().nullable().optional(),
  sourceVersions: z.array(
    z.object({
      name: z.string(),
      url: z.string().nullable().optional(),
      version: z.string(),
      retrievedAt: z.string().nullable().optional(),
      evidenceMode: z.string().nullable().optional(),
      licenseNote: z.string().nullable().optional(),
    }),
  ),
  reasonCodeLabels: z.record(z.string(), z.string()),
  createdAt: z.string(),
  completedAt: z.string().nullable().optional(),
  stops: z.array(portfolioStopSchema),
})

const scenarioSchema = z.object({
  scenarioId: z.string(),
  name: z.string(),
  heatJobId: z.string(),
  shelterSlots: z.number(),
  equityWeight: z.number(),
  minimumEquityShare: z.number(),
  formulaVersion: z.string(),
  createdAt: z.string(),
  heatJob: heatJobSchema,
  latestRunId: z.string().nullable().optional(),
})

export type Health = z.infer<typeof healthSchema>
export type SourceBootstrap = z.infer<typeof snapshotSchema>
export type HeatJob = z.infer<typeof heatJobSchema>
export type PortfolioRun = z.infer<typeof portfolioRunSchema>
export type HeatmapLayer = {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    geometry: { type: string; coordinates: unknown }
    properties: { value?: number; metric?: string }
  }>
}

export interface ScenarioView {
  scenarioId: string
  portfolioId: string
  name: string
  corridorName: string
  runtimeMode: 'LIVE' | 'CACHED_LIVE' | 'DEMO_FIXTURE'
  status: string
  solverStatus: string
  createdAt: string
  completedAt: string
  shelterSlots: number
  equityWeight: number
  minimumEquityShare: number
  thresholdFahrenheit: number
  metricName: string
  formulaVersion: string
  objectiveValue: number
  baselineValue: number
  sourceVersions: ScenarioFixture['sourceVersions']
  stops: Stop[]
  heatJobId?: string
  providerActivityId?: string | null
  heatCellCount?: number
  heatmap?: HeatmapLayer | null
  reasonCodeLabels?: Record<string, string>
  solverVersion?: string | null
  infeasibleReason?: string | null
}

export async function getHealth(): Promise<Health> {
  return healthSchema.parse(await request('/api/health'))
}

export async function getSourceSnapshots(): Promise<SourceBootstrap> {
  return snapshotSchema.parse(await request('/api/v1/source-snapshots'))
}

export async function createHeatJob(body: {
  aoi: Record<string, unknown>
  startDate: string
  filterType?: number
  endDate?: string
  thresholdFahrenheit?: number
  analyticType?: string
}): Promise<HeatJob> {
  return heatJobSchema.parse(
    await request('/api/v1/heat-jobs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  )
}

export async function getHeatJob(jobId: string): Promise<HeatJob> {
  return heatJobSchema.parse(await request(`/api/v1/heat-jobs/${jobId}`))
}

export async function waitForHeatJob(
  jobId: string,
  onUpdate?: (job: HeatJob) => void,
  timeoutMs = 180_000,
): Promise<HeatJob> {
  const started = Date.now()
  let job = await getHeatJob(jobId)
  onUpdate?.(job)
  while (job.pollRecommended && Date.now() - started < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000))
    job = await getHeatJob(jobId)
    onUpdate?.(job)
  }
  if (job.state !== 'COMPLETED') {
    throw new ApiError(
      job.errorCode ?? 'HEAT_JOB_INCOMPLETE',
      job.errorMessage ?? `Heat job ended in state ${job.state}.`,
    )
  }
  return job
}

export async function createScenario(body: {
  heatJobId: string
  name: string
  shelterSlots: number
  equityWeight: number
  minimumEquityShare: number
}) {
  return scenarioSchema.parse(
    await request('/api/v1/scenarios', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  )
}

export async function getScenario(scenarioId: string) {
  return scenarioSchema.parse(await request(`/api/v1/scenarios/${scenarioId}`))
}

export async function createRun(scenarioId: string): Promise<PortfolioRun> {
  return portfolioRunSchema.parse(
    await request(`/api/v1/scenarios/${scenarioId}/runs`, { method: 'POST' }),
  )
}

export async function getPortfolioRun(runId: string): Promise<PortfolioRun> {
  return portfolioRunSchema.parse(await request(`/api/v1/portfolio-runs/${runId}`))
}

export async function getHeatmap(jobId: string): Promise<HeatmapLayer | null> {
  try {
    const payload = await request<HeatmapLayer>(`/api/v1/heat-jobs/${jobId}/heatmap`)
    if (payload?.type === 'FeatureCollection') return payload
  } catch {
    return null
  }
  return null
}

export function exportCsvUrl(runId: string) {
  return `/api/v1/portfolio-runs/${runId}/export.csv`
}

function toStop(item: z.infer<typeof portfolioStopSchema>): Stop {
  return {
    stopId: item.stopId,
    name: item.name,
    context: item.heatJoinMethod.replaceAll('_', ' ').toLowerCase(),
    longitude: item.longitude,
    latitude: item.latitude,
    shelterCount: item.shelterCount,
    ridershipValue: item.ridershipValue,
    exceedanceHours: item.exceedanceHours,
    sviPercentile: item.sviPercentile,
    heatComponent: item.heatComponent,
    ridershipComponent: item.ridershipComponent,
    equityComponent: item.equityComponent,
    finalScore: item.finalScore,
    selected: item.selected,
    baselineSelected: item.baselineSelected,
    rank: item.rank,
    reasonCodes: item.reasonCodes,
  }
}

export function viewFromRun(run: PortfolioRun, heatmap?: HeatmapLayer | null): ScenarioView {
  return {
    scenarioId: run.scenarioId,
    portfolioId: run.runId,
    name: run.scenarioName,
    corridorName: 'Central / 7th Avenue corridor',
    runtimeMode: run.runtimeMode,
    status: run.state,
    solverStatus: run.solverStatus ?? run.state,
    createdAt: run.createdAt,
    completedAt: run.completedAt ?? run.createdAt,
    shelterSlots: run.shelterSlots,
    equityWeight: run.equityWeight,
    minimumEquityShare: run.minimumEquityShare,
    thresholdFahrenheit: run.thresholdFahrenheit ?? 104,
    metricName: run.metricName,
    formulaVersion: run.formulaVersion,
    objectiveValue: run.objectiveValue ?? 0,
    baselineValue: run.baselineValue ?? 0,
    sourceVersions: run.sourceVersions.map((source) => ({
      name: source.name,
      version: source.version,
      retrievedAt: source.retrievedAt ?? run.createdAt,
      evidence: [source.evidenceMode, source.licenseNote].filter(Boolean).join(' · ') || source.version,
    })),
    stops: run.stops.map(toStop),
    heatJobId: undefined,
    heatmap: heatmap ?? null,
    reasonCodeLabels: run.reasonCodeLabels,
    solverVersion: run.solverVersion,
    infeasibleReason: run.infeasibleReason,
  }
}

export async function loadLivePortfolio(runId: string): Promise<ScenarioView> {
  const run = await getPortfolioRun(runId)
  const scenario = await getScenario(run.scenarioId)
  const heatmap = await getHeatmap(scenario.heatJobId)
  const view = viewFromRun(run, heatmap)
  view.heatJobId = scenario.heatJobId
  view.providerActivityId = scenario.heatJob.providerActivityId
  view.heatCellCount = scenario.heatJob.heatCellCount
  return view
}

export async function loadLiveScenario(scenarioId: string, runId?: string): Promise<ScenarioView> {
  const scenario = await getScenario(scenarioId)
  const resolvedRunId = runId || scenario.latestRunId
  if (!resolvedRunId) {
    throw new ApiError('NO_RUN', 'This scenario does not have a portfolio run yet.')
  }
  const [run, heatmap] = await Promise.all([
    getPortfolioRun(resolvedRunId),
    getHeatmap(scenario.heatJobId),
  ])
  const view = viewFromRun(run, heatmap)
  view.heatJobId = scenario.heatJobId
  view.providerActivityId = scenario.heatJob.providerActivityId
  view.heatCellCount = scenario.heatJob.heatCellCount
  return view
}

export function loadFixtureView(options: Parameters<typeof createScenarioFixture>[0] = {}): ScenarioView {
  return { ...createScenarioFixture(options), heatmap: null }
}

export function modeTone(mode: string): 'success' | 'fixture' | 'warning' | 'neutral' {
  if (mode === 'LIVE') return 'success'
  if (mode === 'CACHED_LIVE') return 'success'
  if (mode === 'DEMO_FIXTURE') return 'fixture'
  return 'neutral'
}

export function modeLabel(mode: string) {
  if (mode === 'LIVE') return 'Live FortyGuard'
  if (mode === 'CACHED_LIVE') return 'Cached live FortyGuard'
  if (mode === 'DEMO_FIXTURE') return 'Demo fixture'
  return mode
}
