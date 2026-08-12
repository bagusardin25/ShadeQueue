import { z } from 'zod'

const rawStops = [
  ['SQ-101', 'Central Ave & Roosevelt St', 'Arts District', -112.07392, 33.45873, 0, 1640, 7.8, 0.61],
  ['SQ-102', 'Central Ave & McDowell Rd', 'Library approach', -112.07383, 33.46512, 0, 1810, 6.1, 0.72],
  ['SQ-103', 'Central Ave & Thomas Rd', 'Medical campus', -112.07369, 33.48071, 0, 1490, 9.4, 0.86],
  ['SQ-104', 'Central Ave & Osborn Rd', 'Midtown transfer', -112.07353, 33.48754, 0, 1370, 10.2, 0.91],
  ['SQ-105', 'Central Ave & Indian School Rd', 'Northbound platform', -112.07332, 33.49505, 0, 2025, 5.7, 0.58],
  ['SQ-106', 'Central Ave & Campbell Ave', 'Neighborhood connector', -112.0731, 33.50152, 0, 1080, 11.6, 0.94],
  ['SQ-107', 'Central Ave & Highland Ave', 'Retail frontage', -112.07286, 33.50582, 1, 1330, 8.8, 0.67],
  ['SQ-108', '7th Ave & Van Buren St', 'West transfer', -112.08292, 33.45142, 0, 1260, 10.7, 0.82],
  ['SQ-109', '7th Ave & Roosevelt St', 'Community services', -112.08267, 33.45895, 0, 930, 12.4, 0.96],
  ['SQ-110', '7th Ave & McDowell Rd', 'Southbound platform', -112.08242, 33.46533, 0, 1760, 6.4, 0.69],
  ['SQ-111', '7th Ave & Thomas Rd', 'Hospital connector', -112.08198, 33.48083, 0, 1180, 10.9, 0.88],
  ['SQ-112', '7th Ave & Osborn Rd', 'School crossing', -112.08171, 33.48771, 0, 990, 11.8, 0.92],
  ['SQ-113', '7th Ave & Indian School Rd', 'Civic center approach', -112.08143, 33.49516, 0, 1580, 7.1, 0.74],
  ['SQ-114', '7th Ave & Camelback Rd', 'North transfer', -112.08109, 33.50914, 1, 2180, 5.2, 0.54],
  ['SQ-115', '1st Ave & Jefferson St', 'Downtown connector', -112.07592, 33.44651, 0, 1875, 6.8, 0.63],
  ['SQ-116', '1st Ave & Fillmore St', 'Senior services', -112.0756, 33.45412, 0, 850, 12.8, 0.98],
] as const

export const stopSchema = z.object({
  stopId: z.string(),
  name: z.string(),
  context: z.string(),
  longitude: z.number(),
  latitude: z.number(),
  shelterCount: z.number().int().nonnegative(),
  ridershipValue: z.number().nonnegative(),
  exceedanceHours: z.number().nonnegative(),
  sviPercentile: z.number().min(0).max(1),
  heatComponent: z.number().min(0).max(100),
  ridershipComponent: z.number().min(0).max(100),
  equityComponent: z.number().min(0).max(100),
  finalScore: z.number().min(0).max(100),
  selected: z.boolean(),
  baselineSelected: z.boolean(),
  rank: z.number().int().positive().nullable(),
  reasonCodes: z.array(z.string()),
})

export const scenarioFixtureSchema = z.object({
  scenarioId: z.string(),
  portfolioId: z.string(),
  name: z.string(),
  corridorName: z.string(),
  runtimeMode: z.literal('DEMO_FIXTURE'),
  status: z.literal('COMPLETED'),
  solverStatus: z.literal('OPTIMAL'),
  createdAt: z.iso.datetime(),
  completedAt: z.iso.datetime(),
  shelterSlots: z.number().int().positive(),
  equityWeight: z.number().min(0).max(1),
  minimumEquityShare: z.number().min(0).max(1),
  thresholdFahrenheit: z.number(),
  metricName: z.string(),
  formulaVersion: z.string(),
  objectiveValue: z.number(),
  baselineValue: z.number(),
  sourceVersions: z.array(
    z.object({
      name: z.string(),
      version: z.string(),
      retrievedAt: z.iso.datetime(),
      evidence: z.string(),
    }),
  ),
  stops: z.array(stopSchema),
})

export type Stop = z.infer<typeof stopSchema>
export type ScenarioFixture = z.infer<typeof scenarioFixtureSchema>

export interface FixtureOptions {
  state?: string
  shelterSlots?: number
  equityWeight?: number
  minimumEquityShare?: number
}

export function createScenarioFixture(options: FixtureOptions = {}): ScenarioFixture {
  const shelterSlots = Math.min(12, Math.max(5, Math.round(options.shelterSlots ?? 10)))
  const equityWeight = Math.min(0.8, Math.max(0, options.equityWeight ?? 0.45))
  const minimumEquityShare = Math.min(0.6, Math.max(0, options.minimumEquityShare ?? 0.4))
  const ridershipValues = rawStops.map((stop) => stop[6])
  const exceedanceValues = rawStops.map((stop) => stop[7])
  const maxRidership = Math.max(...ridershipValues)
  const maxExceedance = Math.max(...exceedanceValues)

  const scored = rawStops.map((stop) => {
    const [stopId, name, context, longitude, latitude, shelterCount, ridershipValue, exceedanceHours, sviPercentile] = stop
    const ridershipNormalized = ridershipValue / maxRidership
    const rawScore = ridershipNormalized * exceedanceHours * (1 + equityWeight * sviPercentile)
    return {
      stopId,
      name,
      context,
      longitude,
      latitude,
      shelterCount,
      ridershipValue,
      exceedanceHours,
      sviPercentile,
      ridershipComponent: ridershipNormalized * 100,
      heatComponent: (exceedanceHours / maxExceedance) * 100,
      equityComponent: sviPercentile * 100,
      rawScore,
    }
  })

  const maxRawScore = Math.max(...scored.map((stop) => stop.rawScore))
  const eligible = scored.filter((stop) => stop.shelterCount === 0)
  const optimized = [...eligible].sort((a, b) => b.rawScore - a.rawScore).slice(0, shelterSlots)
  const requiredHighEquity = Math.ceil(shelterSlots * minimumEquityShare)
  const highEquitySelected = optimized.filter((stop) => stop.sviPercentile >= 0.75)
  if (highEquitySelected.length < requiredHighEquity) {
    const replacements = [...eligible]
      .filter((stop) => stop.sviPercentile >= 0.75 && !optimized.some((item) => item.stopId === stop.stopId))
      .sort((a, b) => b.rawScore - a.rawScore)
    while (optimized.filter((stop) => stop.sviPercentile >= 0.75).length < requiredHighEquity && replacements.length > 0) {
      const replacement = replacements.shift()
      const replaceIndex = optimized
        .map((stop, index) => ({ stop, index }))
        .filter(({ stop }) => stop.sviPercentile < 0.75)
        .sort((a, b) => a.stop.rawScore - b.stop.rawScore)[0]?.index
      if (replacement && replaceIndex !== undefined) optimized[replaceIndex] = replacement
    }
  }
  const optimizedIds = new Set(optimized.map((stop) => stop.stopId))
  const baselineIds = new Set(
    [...eligible]
      .sort((a, b) => b.ridershipValue - a.ridershipValue)
      .slice(0, shelterSlots)
      .map((stop) => stop.stopId),
  )
  const rankedIds = [...eligible]
    .sort((a, b) => b.rawScore - a.rawScore)
    .map((stop) => stop.stopId)

  const stops: Stop[] = scored.map((stop) => {
    const selected = optimizedIds.has(stop.stopId)
    const reasons = []
    if (stop.exceedanceHours >= 10) reasons.push('HIGH_HEAT_EXPOSURE')
    if (stop.sviPercentile >= 0.85) reasons.push('HIGH_SOCIAL_VULNERABILITY')
    if (stop.ridershipValue >= 1500) reasons.push('HIGH_SOURCE_RIDERSHIP')
    if (stop.shelterCount > 0) reasons.push('EXISTING_SHELTER')
    if (selected && reasons.length === 0) reasons.push('BALANCED_PORTFOLIO_VALUE')

    return {
      ...stop,
      finalScore: (stop.rawScore / maxRawScore) * 100,
      selected,
      baselineSelected: baselineIds.has(stop.stopId),
      rank: selected ? rankedIds.indexOf(stop.stopId) + 1 : null,
      reasonCodes: reasons,
    }
  })

  const objectiveValue = stops
    .filter((stop) => stop.selected)
    .reduce((total, stop) => total + stop.finalScore, 0)
  const baselineValue = stops
    .filter((stop) => stop.baselineSelected)
    .reduce((total, stop) => total + stop.finalScore, 0)

  return scenarioFixtureSchema.parse({
    scenarioId: 'phoenix-central-fixture',
    portfolioId: 'portfolio-fixture-001',
    name: 'Central Phoenix heat scenario',
    corridorName: 'Central / 7th Avenue corridor',
    runtimeMode: 'DEMO_FIXTURE',
    status: 'COMPLETED',
    solverStatus: 'OPTIMAL',
    createdAt: '2026-08-12T14:04:00.000Z',
    completedAt: '2026-08-12T14:04:08.000Z',
    shelterSlots,
    equityWeight,
    minimumEquityShare,
    thresholdFahrenheit: 104,
    metricName: 'Hours above comparison threshold',
    formulaVersion: 'heat-burden-v0.1-fixture',
    objectiveValue,
    baselineValue,
    sourceVersions: [
      {
        name: 'FortyGuard heatmap',
        version: 'Deterministic contract fixture',
        retrievedAt: '2026-08-12T14:04:08.000Z',
        evidence: 'Synthetic values shaped to the planned adapter contract',
      },
      {
        name: 'City of Phoenix bus stops',
        version: 'UI fixture · not a downloaded snapshot',
        retrievedAt: '2026-08-12T14:04:08.000Z',
        evidence: 'Stop identifiers and values are synthetic for frontend development',
      },
      {
        name: 'CDC/ATSDR SVI',
        version: '2022 schema fixture',
        retrievedAt: '2026-08-12T14:04:08.000Z',
        evidence: 'Percentiles are synthetic and only demonstrate the UI contract',
      },
    ],
    stops,
  })
}

export const scenarioFixture = createScenarioFixture()

export async function loadScenarioFixture(options: FixtureOptions = {}) {
  await new Promise((resolve) => window.setTimeout(resolve, 550))
  if (options.state === 'timeout') {
    throw new Error('The provider status check exceeded the demo time budget.')
  }
  const fixture = createScenarioFixture(options)
  if (options.state === 'empty') {
    return scenarioFixtureSchema.parse({ ...fixture, stops: [] })
  }
  return scenarioFixtureSchema.parse(fixture)
}
