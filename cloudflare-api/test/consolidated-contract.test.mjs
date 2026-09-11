import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { runConsolidated } from '../src/consolidated/pipeline.js'

// A minimal JSON Schema (draft 2020-12 subset) validator covering only the
// keywords contracts/consolidated/schema/consolidated.schema.json actually
// uses. Not a general-purpose library: AUTOPILOT.md forbids a new dependency
// unless it is the only reasonable option, and pulling in a full JSON Schema
// library for one contract test is not. Correctness is checked below against
// the same 3 valid + 3 invalid fixtures contracts/consolidated/tests/test_contract.py
// already validates with the real `jsonschema` package on the Python side.
function resolveRef(ref, root) {
  let node = root
  for (const key of ref.replace(/^#\//, '').split('/')) node = node[key]
  return node
}

function typeMatches(type, value) {
  switch (type) {
    case 'object':
      return value !== null && typeof value === 'object' && !Array.isArray(value)
    case 'array':
      return Array.isArray(value)
    case 'string':
      return typeof value === 'string'
    case 'number':
      return typeof value === 'number' && Number.isFinite(value)
    case 'integer':
      return typeof value === 'number' && Number.isInteger(value)
    case 'boolean':
      return typeof value === 'boolean'
    case 'null':
      return value === null
    default:
      return true
  }
}

function validate(schema, data, root = schema, at = '$') {
  const errors = []
  if (schema.$ref) return validate(resolveRef(schema.$ref, root), data, root, at)
  if (schema.const !== undefined && data !== schema.const) errors.push(`${at}: expected const ${JSON.stringify(schema.const)}, got ${JSON.stringify(data)}`)
  if (schema.enum && !schema.enum.includes(data)) errors.push(`${at}: ${JSON.stringify(data)} not in enum ${JSON.stringify(schema.enum)}`)
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type]
    if (!types.some((t) => typeMatches(t, data))) errors.push(`${at}: type mismatch, expected ${types.join('|')}, got ${JSON.stringify(data)}`)
  }
  if (schema.pattern && typeof data === 'string' && !new RegExp(schema.pattern).test(data)) {
    errors.push(`${at}: ${JSON.stringify(data)} does not match pattern ${schema.pattern}`)
  }
  if (typeof data === 'string') {
    if (schema.minLength !== undefined && data.length < schema.minLength) errors.push(`${at}: shorter than minLength`)
    if (schema.maxLength !== undefined && data.length > schema.maxLength) errors.push(`${at}: longer than maxLength`)
  }
  if (typeof data === 'number') {
    if (schema.minimum !== undefined && data < schema.minimum) errors.push(`${at}: below minimum`)
    if (schema.maximum !== undefined && data > schema.maximum) errors.push(`${at}: above maximum`)
    if (schema.exclusiveMinimum !== undefined && data <= schema.exclusiveMinimum) errors.push(`${at}: not exclusive-above minimum`)
  }
  if (Array.isArray(data)) {
    if (schema.maxItems !== undefined && data.length > schema.maxItems) errors.push(`${at}: too many items`)
    if (schema.items) data.forEach((item, i) => errors.push(...validate(schema.items, item, root, `${at}[${i}]`)))
    if (schema.contains) {
      const ok = data.some((item) => validate(schema.contains, item, root, at).length === 0)
      if (!ok) errors.push(`${at}: no item matches 'contains'`)
    }
  }
  if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
    if (schema.minProperties !== undefined && Object.keys(data).length < schema.minProperties) errors.push(`${at}: fewer than minProperties`)
    if (schema.required) for (const key of schema.required) if (!(key in data)) errors.push(`${at}: missing required '${key}'`)
    if (schema.properties) {
      for (const [key, subschema] of Object.entries(schema.properties)) {
        if (key in data) errors.push(...validate(subschema, data[key], root, `${at}.${key}`))
      }
    }
    if (schema.additionalProperties === false) {
      const allowed = new Set(Object.keys(schema.properties || {}))
      for (const key of Object.keys(data)) if (!allowed.has(key)) errors.push(`${at}: unexpected property '${key}'`)
    }
  }
  if (schema.allOf) for (const sub of schema.allOf) errors.push(...validate(sub, data, root, at))
  if (schema.anyOf) {
    const ok = schema.anyOf.some((sub) => validate(sub, data, root, at).length === 0)
    if (!ok) errors.push(`${at}: none of anyOf matched`)
  }
  if (schema.if) {
    const ifOk = validate(schema.if, data, root, at).length === 0
    if (ifOk && schema.then) errors.push(...validate(schema.then, data, root, at))
  }
  if (schema.not) {
    const notOk = validate(schema.not, data, root, at).length === 0
    if (notOk) errors.push(`${at}: matched 'not' schema`)
  }
  return errors
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const schema = JSON.parse(fs.readFileSync(path.join(repoRoot, 'contracts/consolidated/schema/consolidated.schema.json'), 'utf8'))
const fixturesDir = path.join(repoRoot, 'contracts/consolidated/fixtures')

test('the lite validator agrees with contracts/consolidated/tests/test_contract.py on every existing fixture', () => {
  for (const file of fs.readdirSync(fixturesDir)) {
    const data = JSON.parse(fs.readFileSync(path.join(fixturesDir, file), 'utf8'))
    const errors = validate(schema, data)
    const expectValid = file.startsWith('valid-')
    assert.equal(errors.length === 0, expectValid, `${file}: ${errors.join(' | ')}`)
  }
})

test('a real runConsolidated success output matches consolidated.v1, so the schema cannot silently drift from the code', async () => {
  const quote = { sector: 'Technology', industry: 'Semiconductors', quoteType: 'EQUITY' }
  const { consolidated } = await runConsolidated('NVDA', {
    quote,
    fundamentalSignals: [
      { signal: 'BUY', weight: 2 },
      { signal: 'HOLD', weight: 1 },
    ],
    fetchImpl: async (url) => mockYahoo(url),
  })
  const errors = validate(schema, consolidated)
  assert.deepEqual(errors, [])
})

test('a real runConsolidated degraded (errors-populated) output still matches consolidated.v1', async () => {
  const quote = { sector: 'Technology', industry: 'Semiconductors', quoteType: 'EQUITY' }
  const failingFetch = async () => {
    throw new Error('simulated network failure')
  }
  const { consolidated } = await runConsolidated('NVDA', { quote, fetchImpl: failingFetch })
  const errors = validate(schema, consolidated)
  assert.deepEqual(errors, [])
})

// Mirrors consolidated-engine.test.mjs's mock exactly, so this real output is
// produced the same way the Worker itself produces it, not a hand-built stub.
function weekdays(count, start = Date.UTC(2026, 2, 16)) {
  const days = []
  for (let day = start; days.length < count; day += 86_400_000) {
    const weekday = new Date(day).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.push(day)
  }
  return days
}

function chart(stamps, closeAt, meta = {}) {
  const closes = stamps.map((_, index) => closeAt(index))
  return {
    chart: {
      result: [
        {
          meta: { regularMarketPrice: closes.at(-1), instrumentType: 'EQUITY', currency: 'USD', exchangeTimezoneName: 'America/New_York', ...meta },
          timestamp: stamps,
          indicators: {
            quote: [
              {
                open: closes.map((close) => close * 0.998),
                high: closes.map((close) => close * 1.01),
                low: closes.map((close) => close * 0.99),
                close: closes,
                volume: closes.map((_, index) => 1_000_000 + (index % 7) * 50_000),
              },
            ],
            adjclose: [{ adjclose: closes }],
          },
        },
      ],
    },
  }
}

const wave = (base, drift) => (index) => base * (1 + drift) ** index * (1 + 0.04 * Math.sin(index / 6))

function mockYahoo(url) {
  const parsed = new URL(url)
  if (parsed.hostname.includes('cnn.io')) return new Response('blocked', { status: 418 })
  const symbol = decodeURIComponent(parsed.pathname.split('/').pop())
  const interval = parsed.searchParams.get('interval')
  const drift = { SPY: 0.0004, QQQ: 0.0005, '^VIX': 0, '^TNX': 0 }[symbol] ?? 0.0009
  const base = { '^VIX': 16, '^TNX': 4.3 }[symbol] ?? 100
  if (interval === '1d') {
    const days = weekdays(504, Date.UTC(2024, 8, 2)).map((day) => day / 1000 + 13.5 * 3600)
    return new Response(JSON.stringify(chart(days, wave(base, drift))))
  }
  const days = weekdays(84)
  if (interval === '4h') {
    const stamps = days.flatMap((day) => [day / 1000 + 13.5 * 3600, day / 1000 + 17.5 * 3600])
    return new Response(JSON.stringify(chart(stamps, wave(base, drift / 2), { dataGranularity: '4h' })))
  }
  const stamps = days.flatMap((day) => [0, 1, 2, 3, 4, 5, 6].map((hour) => day / 1000 + (13.5 + hour) * 3600))
  return new Response(JSON.stringify(chart(stamps, wave(base, drift / 7), { dataGranularity: '1h' })))
}
