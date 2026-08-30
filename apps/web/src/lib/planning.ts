import type { Stop } from '../data/fixture'

export function selectedPortfolio(stops: Stop[]) {
  return [...stops]
    .filter((stop) => stop.selected)
    .sort((a, b) => b.finalScore - a.finalScore || a.stopId.localeCompare(b.stopId))
}

export function portfolioRankById(stops: Stop[]) {
  const ranks = new Map<string, number>()
  selectedPortfolio(stops).forEach((stop, index) => {
    ranks.set(stop.stopId, index + 1)
  })
  return ranks
}

export function objectiveDelta(objective: number, baseline: number) {
  if (!baseline) return { pct: 0, kind: 'flat' as const }
  const pct = ((objective - baseline) / baseline) * 100
  if (pct > 0.05) return { pct, kind: 'gain' as const }
  if (pct < -0.05) return { pct, kind: 'equity-cost' as const }
  return { pct, kind: 'flat' as const }
}

export function heatSpreadHours(stops: Stop[]) {
  if (stops.length === 0) return { min: 0, max: 0, relative: 0 }
  const values = stops.map((stop) => stop.exceedanceHours)
  const min = Math.min(...values)
  const max = Math.max(...values)
  return { min, max, relative: max === 0 ? 0 : (max - min) / max }
}

export function heatIsUniform(stops: Stop[]) {
  return heatSpreadHours(stops).relative < 0.08
}

export function existingShelterCount(stops: Stop[]) {
  return stops.filter((stop) => stop.shelterCount > 0).length
}

export function selectedReason(stop: Stop) {
  if (!stop.baselineSelected && stop.sviPercentile >= 0.75) {
    return 'Equity swap — high SVI, not in the ridership baseline'
  }
  if (stop.reasonCodes.includes('HIGH_SOURCE_RIDERSHIP')) return 'Demand-led priority'
  if (stop.reasonCodes.includes('HIGH_SOCIAL_VULNERABILITY')) return 'Equity-led priority'
  if (stop.reasonCodes.includes('HIGH_HEAT_EXPOSURE')) return 'Heat-led priority'
  return 'Balanced portfolio value'
}
