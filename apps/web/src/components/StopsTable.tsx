import { useMemo, useState } from 'react'
import { Search, X } from 'lucide-react'
import type { Stop } from '../data/fixture'
import { cn, formatNumber } from '../lib/utils'
import { portfolioRankById } from '../lib/planning'
import { Badge } from './ui/badge'
import { Button } from './ui/button'

type StopFilter = 'all' | 'recommended' | 'baseline' | 'candidate' | 'existing'

interface StopsTableProps {
  stops: Stop[]
  selectedStopId: string
  onSelect: (stopId: string) => void
}

function stopStatus(stop: Stop, pinRank?: number) {
  if (stop.shelterCount > 0) return { label: 'Existing shelter', tone: 'neutral' as const }
  if (stop.selected) return { label: pinRank ? `Pin ${pinRank}` : 'Recommended', tone: 'success' as const }
  if (stop.baselineSelected) return { label: 'Baseline only', tone: 'warning' as const }
  return { label: 'Candidate', tone: 'neutral' as const }
}

export function StopsTable({ stops, selectedStopId, onSelect }: StopsTableProps) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StopFilter>('recommended')
  const pinRanks = useMemo(() => portfolioRankById(stops), [stops])

  const filteredStops = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return [...stops]
      .filter((stop) => {
        if (normalizedQuery && !`${stop.name} ${stop.stopId} ${stop.context}`.toLowerCase().includes(normalizedQuery)) {
          return false
        }
        if (filter === 'recommended') return stop.selected
        if (filter === 'baseline') return stop.baselineSelected
        if (filter === 'candidate') return !stop.selected && stop.shelterCount === 0
        if (filter === 'existing') return stop.shelterCount > 0
        return true
      })
      .sort((a, b) => {
        if (a.selected !== b.selected) return a.selected ? -1 : 1
        return b.finalScore - a.finalScore
      })
  }, [filter, query, stops])

  const clearFilters = () => {
    setQuery('')
    setFilter('all')
  }

  return (
    <section id="stops-table" className="border border-line bg-panel" aria-labelledby="stops-table-title">
      <div className="border-b border-line p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-heat">Accessible map equivalent</p>
            <h2 id="stops-table-title" className="mt-1 text-lg font-extrabold tracking-[-0.03em]">Official corridor stops</h2>
          </div>
          <p className="text-xs text-muted-ink" aria-live="polite">{filteredStops.length} of {stops.length} shown</p>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_10rem]">
          <label className="relative block">
            <span className="sr-only">Search stops</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-ink" aria-hidden="true" />
            <input
              className="field-control pl-9 pr-10"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search stop or ID"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label="Clear stop search"
                className="absolute right-1 top-1/2 grid size-10 -translate-y-1/2 cursor-pointer place-items-center rounded-md text-muted-ink hover:bg-panel-raised focus-visible:outline-2 focus-visible:outline-focus"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            ) : null}
          </label>
          <label>
            <span className="sr-only">Filter stops</span>
            <select className="field-control" value={filter} onChange={(event) => setFilter(event.target.value as StopFilter)}>
              <option value="all">All stops</option>
              <option value="recommended">Recommended</option>
              <option value="baseline">Baseline set</option>
              <option value="candidate">Other candidates</option>
              <option value="existing">Existing shelter</option>
            </select>
          </label>
        </div>
      </div>

      {filteredStops.length === 0 ? (
        <div className="grid min-h-72 place-items-center p-6 text-center">
          <div>
            <Search className="mx-auto mb-3 text-muted-ink" aria-hidden="true" />
            <h3 className="font-bold">No stops match this view</h3>
            <p className="mt-1 text-sm text-muted-ink">Clear the search and filters to restore the corridor list.</p>
            <Button className="mt-4" variant="secondary" onClick={clearFilters}>Clear filters</Button>
          </div>
        </div>
      ) : (
        <>
          <div className="hidden max-h-[28rem] overflow-auto md:block">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="sticky top-0 z-10 bg-panel-raised text-[0.68rem] uppercase tracking-[0.1em] text-muted-ink">
                <tr>
                  <th className="border-b border-line px-4 py-3 font-bold">Stop</th>
                  <th className="border-b border-line px-3 py-3 font-bold">Portfolio</th>
                  <th className="border-b border-line px-3 py-3 text-right font-bold">Heat h</th>
                  <th className="border-b border-line px-3 py-3 text-right font-bold">Source value</th>
                  <th className="border-b border-line px-4 py-3 text-right font-bold">Score</th>
                </tr>
              </thead>
              <tbody>
                {filteredStops.map((stop) => {
                  const status = stopStatus(stop, pinRanks.get(stop.stopId))
                  const isSelected = selectedStopId === stop.stopId
                  return (
                    <tr key={stop.stopId} className={cn('border-b border-line/80 last:border-b-0', isSelected && 'bg-[#e8f3ef]')}>
                      <th scope="row" className="px-4 py-3 font-normal">
                        <button
                          type="button"
                          onClick={() => onSelect(stop.stopId)}
                          aria-pressed={isSelected}
                          className="min-h-11 cursor-pointer rounded-sm text-left font-bold leading-tight text-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                        >
                          {stop.name}
                          <span className="mt-1 block font-mono text-[0.68rem] font-medium tracking-normal text-muted-ink">{stop.stopId}</span>
                        </button>
                      </th>
                      <td className="px-3 py-3"><Badge tone={status.tone}>{status.label}</Badge></td>
                      <td className="metric-numeral px-3 py-3 text-right">{stop.exceedanceHours.toFixed(1)}</td>
                      <td className="metric-numeral px-3 py-3 text-right">{formatNumber(stop.ridershipValue)}</td>
                      <td className="metric-numeral px-4 py-3 text-right font-bold">{stop.finalScore.toFixed(1)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <ul className="divide-y divide-line md:hidden">
            {filteredStops.map((stop) => {
              const status = stopStatus(stop, pinRanks.get(stop.stopId))
              const isSelected = selectedStopId === stop.stopId
              return (
                <li key={stop.stopId} className={cn('p-3', isSelected && 'bg-[#e8f3ef]')}>
                  <button
                    type="button"
                    onClick={() => onSelect(stop.stopId)}
                    aria-pressed={isSelected}
                    className="w-full cursor-pointer rounded-sm p-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                  >
                    <span className="flex items-start justify-between gap-3">
                      <span>
                        <strong className="block text-sm leading-5">{stop.name}</strong>
                        <span className="mt-1 block font-mono text-[0.68rem] text-muted-ink">{stop.stopId}</span>
                      </span>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </span>
                    <span className="mt-3 grid grid-cols-3 gap-2 border-t border-line/70 pt-3 text-xs text-muted-ink">
                      <span>Heat <b className="metric-numeral block text-sm text-ink">{stop.exceedanceHours.toFixed(1)} h</b></span>
                      <span>Source <b className="metric-numeral block text-sm text-ink">{formatNumber(stop.ridershipValue)}</b></span>
                      <span>Score <b className="metric-numeral block text-sm text-ink">{stop.finalScore.toFixed(1)}</b></span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}
