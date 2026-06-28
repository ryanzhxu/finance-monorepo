import axios from 'axios'
import type {
  AnalysisResponse,
  AnalystHealthResponse,
  EntryConfluenceResponse,
  ScreenResponse,
  ScreenerHealthResponse,
  TrendingScreenResponse,
} from './types'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() || null
const analystBaseUrl = apiBaseUrl ?? import.meta.env.VITE_ANALYST_URL ?? 'http://localhost:8001'
const screenerBaseUrl = apiBaseUrl ?? import.meta.env.VITE_SCREENER_URL ?? 'http://localhost:8002'

const analystClient = axios.create({
  baseURL: analystBaseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
})

const screenerClient = axios.create({
  baseURL: screenerBaseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
})

function toErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data
    if (typeof detail === 'string') {
      return detail
    }
    if (
      detail &&
      typeof detail === 'object' &&
      'detail' in detail &&
      typeof detail.detail === 'string'
    ) {
      return detail.detail
    }
    return error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return 'Unexpected request failure'
}

export async function fetchAnalysis(symbol: string, signal?: AbortSignal): Promise<AnalysisResponse> {
  try {
    const response = await analystClient.post<AnalysisResponse>('/analyze', {
      symbol,
      include_narrative: false,
    }, {
      signal,
    })
    return response.data
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}

export async function fetchEntryConfluence(
  symbol: string,
  lookbackDays?: number,
  signal?: AbortSignal,
): Promise<EntryConfluenceResponse> {
  try {
    const response = await analystClient.post<EntryConfluenceResponse>('/entry/confluence', {
      symbol,
      ...(lookbackDays ? { lookback_days: lookbackDays } : {}),
    }, {
      signal,
    })
    return response.data
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}

export async function fetchAnalyzeBundle(symbol: string, signal?: AbortSignal): Promise<{
  analysis: AnalysisResponse
  confluence: EntryConfluenceResponse
}> {
  try {
    const [analysis, confluence] = await Promise.all([
      fetchAnalysis(symbol, signal),
      fetchEntryConfluence(symbol, undefined, signal),
    ])
    return { analysis, confluence }
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}

export async function fetchUndervaluedScreen(): Promise<ScreenResponse> {
  try {
    const response = await screenerClient.post<ScreenResponse>('/screen/undervalued', {
      universe: 'SP500',
      limit: 25,
      include_analysis: true,
      include_narrative: false,
    })
    return response.data
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}

export async function fetchTrendingScreen(): Promise<TrendingScreenResponse> {
  try {
    const response = await screenerClient.post<TrendingScreenResponse>('/screen/trending', {
      universe: 'SP500',
      limit: 25,
      include_analysis: true,
      include_narrative: false,
      lookback_days: [3, 5],
      sources: ['news', 'yahoo_trending'],
    })
    return response.data
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}

export async function fetchAnalystHealth(): Promise<AnalystHealthResponse> {
  try {
    const response = await analystClient.get<AnalystHealthResponse>('/health')
    return response.data
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}

export async function fetchSymbolSearch(
  q: string,
): Promise<Array<{ symbol: string; name: string; exchange: string; type: string }>> {
  if (!q || q.length < 1) return []
  try {
    const resp = await analystClient.get<
      Array<{ symbol: string; name: string; exchange: string; type: string }>
    >('/search', { params: { q, limit: 6 } })
    return resp.data
  } catch {
    return []
  }
}

export async function fetchScreenerHealth(): Promise<ScreenerHealthResponse> {
  try {
    const response = await screenerClient.get<ScreenerHealthResponse>('/screen/health')
    return response.data
  } catch (error) {
    throw new Error(toErrorMessage(error), { cause: error })
  }
}
