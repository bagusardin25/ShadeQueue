import { ArrowLeft, MapPinOff } from 'lucide-react'
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-[65vh] max-w-2xl items-center px-4 py-16 sm:px-6">
      <section className="w-full border border-line bg-panel p-6 sm:p-8" aria-labelledby="not-found-title">
        <MapPinOff className="size-7 text-heat" aria-hidden="true" />
        <p className="mt-5 text-xs font-bold uppercase tracking-[0.14em] text-heat">Route not found</p>
        <h1 id="not-found-title" className="mt-2 text-3xl font-extrabold tracking-[-0.045em]">This planning view is outside the corridor.</h1>
        <p className="mt-3 leading-7 text-muted-ink">Return to the guided scenario to restore the deterministic fixture journey.</p>
        <Link to="/scenarios/new" className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-md bg-action px-4 text-sm font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
          <ArrowLeft className="size-4" aria-hidden="true" /> Start a scenario
        </Link>
      </section>
    </div>
  )
}
