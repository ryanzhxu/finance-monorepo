export type SymbolSuggestion = {
  symbol: string
  name: string
}

export type SuggestionsSnapshot = {
  suggestions: SymbolSuggestion[]
  showSuggestions: boolean
  activeSuggestionIndex: number
}

export const CLOSED_SUGGESTIONS: SuggestionsSnapshot = {
  suggestions: [],
  showSuggestions: false,
  activeSuggestionIndex: -1,
}

/**
 * The symbol search is debounced and async, so an older request can resolve
 * after a newer one (or after the dropdown was closed). Compare the id the
 * request was issued with against the latest id to tell a stale response
 * from the current one.
 */
export function isStaleSuggestionResponse(requestId: number, latestRequestId: number): boolean {
  return requestId !== latestRequestId
}

export function suggestionsAfterSearch(results: SymbolSuggestion[]): SuggestionsSnapshot {
  return {
    suggestions: results,
    showSuggestions: results.length > 0,
    activeSuggestionIndex: results.length > 0 ? 0 : -1,
  }
}

export function suggestionsAfterArrow(
  current: SuggestionsSnapshot,
  delta: 1 | -1,
): SuggestionsSnapshot {
  if (current.suggestions.length === 0) {
    return current
  }
  const count = current.suggestions.length
  const nextIndex = ((current.activeSuggestionIndex + delta) % count + count) % count
  return { ...current, showSuggestions: true, activeSuggestionIndex: nextIndex }
}
