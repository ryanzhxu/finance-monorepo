import { useState } from 'react'
import Analyze from './views/Analyze'
import Health from './views/Health'
import Screener from './views/Screener'

type ViewKey = 'analyze' | 'screener' | 'health'

type AnalyzeSelection = {
  value: string
  nonce: number
}

const tabs: Array<{ key: ViewKey; label: string }> = [
  { key: 'analyze', label: 'Analyze' },
  { key: 'screener', label: 'Screener' },
  { key: 'health', label: 'Health' },
]

function App() {
  const [activeView, setActiveView] = useState<ViewKey>('analyze')
  const [requestedSymbol, setRequestedSymbol] = useState<AnalyzeSelection | null>(null)

  return (
    <div className="min-h-screen bg-transparent px-4 py-6 text-slate-900 sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-7xl flex-col overflow-hidden rounded-[2rem] border border-slate-200 bg-white/90 shadow-[0_30px_80px_rgba(15,23,42,0.12)] backdrop-blur">
        <header className="border-b border-slate-200 bg-[linear-gradient(135deg,rgba(148,163,184,0.08),rgba(245,158,11,0.08))] px-6 py-6 sm:px-8">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
                finance-monorepo
              </p>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
                  Market Analysis Console
                </h1>
                <p className="mt-2 max-w-2xl text-sm text-slate-600 sm:text-base">
                  A focused console for single-symbol analysis, screening, and service health checks.
                </p>
              </div>
            </div>
            <nav className="flex flex-wrap gap-2 rounded-full border border-slate-200 bg-white/80 p-1 shadow-sm">
              {tabs.map((tab) => {
                const isActive = activeView === tab.key
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveView(tab.key)}
                    className={[
                      'rounded-full px-4 py-2 text-sm font-medium transition',
                      isActive
                        ? 'bg-slate-900 text-white shadow-sm'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                    ].join(' ')}
                  >
                    {tab.label}
                  </button>
                )
              })}
            </nav>
          </div>
        </header>

        <main className="flex-1 px-6 py-6 sm:px-8">
          {activeView === 'analyze' ? (
            <Analyze
              key={requestedSymbol?.nonce ?? 'analyze-default'}
              requestedSymbol={requestedSymbol}
            />
          ) : null}
          {activeView === 'screener' ? (
            <Screener
              onAnalyzeSymbol={(symbol) => {
                setRequestedSymbol({ value: symbol, nonce: Date.now() })
                setActiveView('analyze')
              }}
            />
          ) : null}
          {activeView === 'health' ? <Health /> : null}
        </main>
      </div>
    </div>
  )
}

export default App
