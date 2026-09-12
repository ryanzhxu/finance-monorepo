import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CLOSED_SUGGESTIONS,
  isStaleSuggestionResponse,
  suggestionsAfterArrow,
  suggestionsAfterSearch,
} from '../src/symbolSuggestions.ts'

const suggestion = (symbol) => ({ symbol, name: `${symbol} Inc.` })

test('isStaleSuggestionResponse: a response whose id no longer matches the latest issued id is stale', () => {
  assert.equal(isStaleSuggestionResponse(1, 2), true)
})

test('isStaleSuggestionResponse: a response matching the latest issued id is current', () => {
  assert.equal(isStaleSuggestionResponse(2, 2), false)
})

test('suggestionsAfterSearch: results open the dropdown with the first suggestion active', () => {
  const results = [suggestion('UNH'), suggestion('UNP')]
  assert.deepEqual(suggestionsAfterSearch(results), {
    suggestions: results,
    showSuggestions: true,
    activeSuggestionIndex: 0,
  })
})

test('suggestionsAfterSearch: no results closes the dropdown', () => {
  assert.deepEqual(suggestionsAfterSearch([]), {
    suggestions: [],
    showSuggestions: false,
    activeSuggestionIndex: -1,
  })
})

test('suggestionsAfterArrow: moving down wraps from the last suggestion to the first', () => {
  const state = {
    suggestions: [suggestion('A'), suggestion('B'), suggestion('C')],
    showSuggestions: true,
    activeSuggestionIndex: 2,
  }
  assert.equal(suggestionsAfterArrow(state, 1).activeSuggestionIndex, 0)
})

test('suggestionsAfterArrow: moving up wraps from the first suggestion to the last', () => {
  const state = {
    suggestions: [suggestion('A'), suggestion('B'), suggestion('C')],
    showSuggestions: true,
    activeSuggestionIndex: 0,
  }
  assert.equal(suggestionsAfterArrow(state, -1).activeSuggestionIndex, 2)
})

test('suggestionsAfterArrow: an empty suggestion list is a no-op', () => {
  assert.deepEqual(suggestionsAfterArrow(CLOSED_SUGGESTIONS, 1), CLOSED_SUGGESTIONS)
})

test('suggestionsAfterArrow: reopens the dropdown if it had been closed with suggestions still loaded', () => {
  const state = {
    suggestions: [suggestion('A')],
    showSuggestions: false,
    activeSuggestionIndex: -1,
  }
  assert.equal(suggestionsAfterArrow(state, 1).showSuggestions, true)
})
