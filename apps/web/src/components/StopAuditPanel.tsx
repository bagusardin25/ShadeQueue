import { Ban, BusFront, CheckCircle2, ThermometerSun, UsersRound } from 'lucide-react'
import type { Stop } from '../data/fixture'
import { formatNumber } from '../lib/utils'
import { Badge } from './ui/badge'

const reasonLabels: Record<string, string> = {
  HIGH_HEAT_EXPOSURE: 'High heat exposure',
  HIGH_SOCIAL_VULNERABILITY: 'High SVI percentile',
  HIGH_SOURCE_RIDERSHIP: 'High source-provided ridership',
  EXISTING_SHELTER: 'Existing shelter excludes a new allocation',
  BALANCED_PORTFOLIO_VALUE: 'Balanced value across score components',
}

interface StopAuditPanelProps {
  stop: Stop
}

const components = [
  { key: 'heatComponent' as const, label: 'Heat', color: 'bg-heat' },
  { key: 'ridershipComponent' as const, label: 'Source value', color: 'bg-action' },
  { key: 'equityComponent' as const, label: 'Equity', color: 'bg-sun' },
]

export function StopAuditPanel({ stop }: StopAuditPanelProps) {
  const excluded = stop.shelterCount > 0
  return (
    <section className="border border-ink bg-panel" aria-labelledby="audit-panel-title">
      <div className="thermal-rule" />
      <div className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)] lg:p-6">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={excluded ? 'neutral' : stop.selected ? 'success' : 'warning'}>
              {excluded ? 'Excluded' : stop.selected ? `Recommended · rank ${stop.rank}` : 'Not selected'}
            </Badge>
            <span className="font-mono text-xs text-muted-ink">{stop.stopId}</span>
          </div>
          <h2 id="audit-panel-title" className="mt-3 text-2xl font-extrabold tracking-[-0.035em]">{stop.name}</h2>
          <p className="mt-1 text-sm text-muted-ink">{stop.context}</p>

          <div className="mt-6 grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
            <div className="bg-panel p-3">
              <ThermometerSun className="mb-2 size-4 text-heat" aria-hidden="true" />
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Exceedance</p>
              <p className="metric-numeral mt-1 text-xl font-bold">{stop.exceedanceHours.toFixed(1)} h</p>
            </div>
            <div className="bg-panel p-3">
              <BusFront className="mb-2 size-4 text-action" aria-hidden="true" />
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Source value</p>
              <p className="metric-numeral mt-1 text-xl font-bold">{formatNumber(stop.ridershipValue)}</p>
            </div>
            <div className="bg-panel p-3">
              <UsersRound className="mb-2 size-4 text-[#9a6c08]" aria-hidden="true" />
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.1em] text-muted-ink">SVI percentile</p>
              <p className="metric-numeral mt-1 text-xl font-bold">{Math.round(stop.sviPercentile * 100)}th</p>
            </div>
            <div className="bg-panel p-3">
              {excluded ? <Ban className="mb-2 size-4 text-muted-ink" aria-hidden="true" /> : <CheckCircle2 className="mb-2 size-4 text-action" aria-hidden="true" />}
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Final score</p>
              <p className="metric-numeral mt-1 text-xl font-bold">{stop.finalScore.toFixed(1)}</p>
            </div>
          </div>

          <div className="mt-5">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted-ink">Reason codes</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {stop.reasonCodes.map((reason) => (
                <li key={reason} className="border border-line bg-panel-raised px-2.5 py-1.5 text-xs font-semibold">
                  {reasonLabels[reason] ?? reason}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="border-l-0 border-line lg:border-l lg:pl-6">
          <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted-ink">Score composition</p>
          <div className="mt-4 space-y-4">
            {components.map(({ key, label, color }) => (
              <div key={key}>
                <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
                  <span className="font-semibold">{label}</span>
                  <span className="metric-numeral font-bold">{stop[key].toFixed(1)}</span>
                </div>
                <div className="h-2.5 overflow-hidden bg-[#e4e1d7]" aria-hidden="true">
                  <div className={`h-full ${color}`} style={{ width: `${stop[key]}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-6 border-t border-line pt-4 text-xs leading-5 text-muted-ink">
            <p><strong className="text-ink">Formula:</strong> normalized source value × exceedance hours × equity multiplier.</p>
            <p className="mt-2">These are synthetic fixture values. They demonstrate the audit contract, not a Phoenix planning recommendation.</p>
          </div>
        </div>
      </div>
    </section>
  )
}
