import { useEffect, useState } from 'react'
import Analyze from './views/Analyze'
import Health from './views/Health'
import Screener from './views/Screener'
import { applyTheme, getStoredTheme, storeTheme, type Theme } from './theme'

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

function ThemeToggle({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-700 dark:bg-slate-900">
      {(['light', 'system', 'dark'] as Theme[]).map((itemTheme) => (
        <button
          key={itemTheme}
          type="button"
          onClick={() => onChange(itemTheme)}
          className={[
            'rounded-md px-3 py-1 text-xs font-medium capitalize transition',
            theme === itemTheme
              ? 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100'
              : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
          ].join(' ')}
        >
          {itemTheme}
        </button>
      ))}
    </div>
  )
}

function App() {
  const [activeView, setActiveView] = useState<ViewKey>('analyze')
  const [requestedSymbol, setRequestedSymbol] = useState<AnalyzeSelection | null>(null)
  const [theme, setTheme] = useState<Theme>(getStoredTheme)

  useEffect(() => {
    if (theme !== 'system') {
      return
    }
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (event: MediaQueryListEvent) =>
      document.documentElement.classList.toggle('dark', event.matches)
    mediaQuery.addEventListener('change', handler)
    return () => mediaQuery.removeEventListener('change', handler)
  }, [theme])

  const handleThemeChange = (nextTheme: Theme) => {
    storeTheme(nextTheme)
    applyTheme(nextTheme)
    setTheme(nextTheme)
  }

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 dark:bg-[#090c12] sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-7xl flex-col overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_30px_80px_rgba(15,23,42,0.12)] dark:border-slate-800 dark:bg-[#0d0f14]">
        <header className="border-b border-slate-200 bg-white px-6 py-6 dark:border-slate-800 dark:bg-[#0d0f14] sm:px-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                finance-monorepo
              </p>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-100 sm:text-4xl">
                  Market Analysis Console
                </h1>
                <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400 sm:text-base">
                  A focused console for single-symbol analysis, screening, and service health checks.
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-3 lg:items-end">
              <ThemeToggle theme={theme} onChange={handleThemeChange} />
              <nav className="flex flex-wrap items-center gap-4">
                {tabs.map((tab) => {
                  const isActive = activeView === tab.key
                  return (
                    <button
                      key={tab.key}
                      type="button"
                      onClick={() => setActiveView(tab.key)}
                      className={[
                        'border-b-2 px-1 pb-2 text-sm font-medium transition',
                        isActive
                          ? 'border-slate-900 text-slate-900 dark:border-slate-100 dark:text-slate-100'
                          : 'border-transparent text-slate-500 dark:text-slate-400',
                      ].join(' ')}
                    >
                      {tab.label}
                    </button>
                  )
                })}
              </nav>
            </div>
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
