import { FileCheck2, MapPinned, Route, SunMedium } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { Badge } from './ui/badge'
import { cn } from '../lib/utils'
import { getHealth, modeLabel, modeTone, readSession } from '../lib/api'

export function AppShell() {
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, retry: 1 })
  const session = typeof window === 'undefined' ? null : readSession()
  const navItems = [
    { label: 'New scenario', to: '/scenarios/new', icon: Route },
    ...(session
      ? [
          {
            label: 'Corridor',
            to: `/scenarios/${session.scenarioId}?run=${session.runId}`,
            icon: MapPinned,
          },
          {
            label: 'Portfolio',
            to: `/portfolios/${session.runId}`,
            icon: FileCheck2,
          },
        ]
      : []),
  ]
  const live = health.data?.liveProviderEnabled
  const mode = live ? 'LIVE' : health.data ? 'DEMO_FIXTURE' : 'unknown'

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-canvas/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[100rem] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6 lg:px-8">
          <NavLink
            to="/"
            className="group flex min-h-11 items-center gap-3 rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            aria-label="ShadeQueue home"
          >
            <span className="grid size-10 place-items-center border border-ink bg-ink text-canvas transition-transform group-hover:-rotate-3">
              <SunMedium className="size-5" strokeWidth={2.25} aria-hidden="true" />
            </span>
            <span>
              <span className="block text-[0.68rem] font-bold uppercase tracking-[0.18em] text-heat">Heat planning lab</span>
              <span className="block text-lg font-extrabold leading-none tracking-[-0.04em]">ShadeQueue</span>
            </span>
          </NavLink>

          <nav className="order-3 flex w-full gap-1 overflow-x-auto sm:order-none sm:ml-auto sm:w-auto" aria-label="Primary navigation">
            {navItems.map(({ label, to, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    'inline-flex min-h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-semibold text-muted-ink transition-colors hover:bg-panel hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
                    isActive && 'bg-panel text-ink shadow-[inset_0_-2px_#c2462f]',
                  )
                }
              >
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </NavLink>
            ))}
          </nav>

          <Badge tone={modeTone(mode)} className="ml-auto sm:ml-0">
            {health.isError ? 'API unreachable' : live ? modeLabel('LIVE') : modeLabel('DEMO_FIXTURE')}
          </Badge>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        <Outlet />
      </main>

      <footer className="border-t border-line bg-panel-raised">
        <div className="mx-auto flex max-w-[100rem] flex-col gap-3 px-4 py-6 text-xs text-muted-ink sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <p>
            <strong className="text-ink">Planning aid only.</strong> Recommendations require qualified human review.
          </p>
          <p className="font-mono uppercase tracking-[0.1em]">No city-system writeback · human decision required</p>
        </div>
      </footer>
    </div>
  )
}
