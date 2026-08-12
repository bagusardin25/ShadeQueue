import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'

const ScenarioBuilderPage = lazy(() =>
  import('./pages/ScenarioBuilderPage').then((module) => ({ default: module.ScenarioBuilderPage })),
)
const ScenarioPage = lazy(() =>
  import('./pages/ScenarioPage').then((module) => ({ default: module.ScenarioPage })),
)
const PortfolioPage = lazy(() =>
  import('./pages/PortfolioPage').then((module) => ({ default: module.PortfolioPage })),
)
const NotFoundPage = lazy(() =>
  import('./pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })),
)

function RouteLoading() {
  return (
    <div className="mx-auto min-h-[70vh] max-w-[100rem] px-4 py-10 sm:px-6 lg:px-8" aria-busy="true" aria-label="Loading planning view">
      <div className="skeleton h-5 w-40" />
      <div className="skeleton mt-5 h-14 max-w-2xl" />
      <div className="skeleton mt-8 h-80 w-full" />
    </div>
  )
}

export function App() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<ScenarioBuilderPage />} />
          <Route path="scenarios/new" element={<ScenarioBuilderPage />} />
          <Route path="scenarios/:scenarioId" element={<ScenarioPage />} />
          <Route path="portfolios/:runId" element={<PortfolioPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
