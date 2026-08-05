import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { I18nProvider } from './i18n'
import { applyTheme, getStoredTheme } from './theme'

const queryClient = new QueryClient()
applyTheme(getStoredTheme())

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <I18nProvider>
      <App />
    </I18nProvider>
  </QueryClientProvider>,
)
