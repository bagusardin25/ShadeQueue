import type { ScenarioView } from '../lib/api'
import {
  existingShelterCount,
  heatIsUniform,
  heatSpreadHours,
  objectiveDelta,
} from '../lib/planning'

export function RunInsights({ data }: { data: ScenarioView }) {
  const live = data.runtimeMode !== 'DEMO_FIXTURE'
  const delta = objectiveDelta(data.objectiveValue, data.baselineValue)
  const spread = heatSpreadHours(data.stops)
  const uniform = heatIsUniform(data.stops)
  const existing = existingShelterCount(data.stops)
  const swapped = data.stops.filter((stop) => stop.selected && !stop.baselineSelected).length
  const notes: string[] = []

  if (!live) {
    notes.push(
      'This view is a labeled DEMO_FIXTURE. It is not City of Phoenix GIS, CDC SVI, or a live FortyGuard heatmap.',
    )
  } else {
    if (uniform) {
      notes.push(
        `Heat is nearly uniform in this window (${spread.min.toFixed(0)}–${spread.max.toFixed(0)} h). Ranking is driven by Phoenix GIS ridership and CDC SVI, not by hotter vs cooler stops.`,
      )
    }
    if (delta.kind === 'equity-cost') {
      notes.push(
        `The high-SVI floor swapped ${swapped} lower-ridership stops into the ${data.shelterSlots}-slot set. Proxy objective is ${Math.abs(delta.pct).toFixed(1)}% below the ridership-only baseline — that is the equity cost, not a solver error.`,
      )
    } else if (delta.kind === 'gain') {
      notes.push(
        `Heat-aware scoring covers ${delta.pct.toFixed(1)}% more of the proxy objective than ranking by ridership alone.`,
      )
    }
    notes.push(
      `Phoenix GIS records a shelter on ${existing} of ${data.stops.length} corridor stops. Missing NBR_SHELTERS values are treated as unsheltered, not as a field survey.`,
    )
  }

  return (
    <aside className="mt-5 border border-[#8d4f09]/30 bg-[#fff6df] px-4 py-4 sm:px-5" aria-label="How to read this run">
      <p className="text-xs font-bold uppercase tracking-[0.12em] text-[#825b08]">How to read this run</p>
      <ul className="mt-2 space-y-2 text-sm leading-6 text-[#66420d]">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </aside>
  )
}
