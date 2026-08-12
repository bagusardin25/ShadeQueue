import { Component, type ErrorInfo, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { App } from './App'
import { Button } from './components/ui/button'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
})

interface ErrorBoundaryState {
  hasError: boolean
}

class AppErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ShadeQueue render failure', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16">
          <section className="w-full border border-line bg-panel p-6 sm:p-8" aria-labelledby="fatal-error-title">
            <AlertTriangle className="mb-5 text-danger" aria-hidden="true" />
            <p className="mb-2 text-xs font-bold uppercase tracking-[0.16em] text-danger">Interface error</p>
            <h1 id="fatal-error-title" className="text-2xl font-bold tracking-[-0.03em]">
              This view could not be rendered.
            </h1>
            <p className="mt-3 max-w-prose text-muted-ink">
              Your planning data has not been submitted. Reload the fixture workspace to recover.
            </p>
            <Button className="mt-6" onClick={() => window.location.reload()}>
              Reload workspace
            </Button>
          </section>
        </main>
      )
    }

    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <AppErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </AppErrorBoundary>,
)
