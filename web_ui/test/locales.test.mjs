// Hand-written locales rot in specific, predictable directions. These checks
// guard the ones that actually apply here.
//
// The repo previously shipped a locale labelled zh-HK that was genuine written
// Cantonese (嘅 / 唔 / 喺 / 冇 / 咗). It was removed rather than converted,
// because a character converter changes glyphs, not words. These tests keep it
// from drifting back in, and keep the two Chinese locales from borrowing each
// other's vocabulary.

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const source = readFileSync(path.join(ROOT, 'src', 'i18n.tsx'), 'utf8')

/** Pull one locale's string values out of the messages object. */
function localeStrings(locale) {
  const key = locale === 'en' ? 'en' : `'${locale}'`
  const start = source.indexOf(`\n  ${key}: {`)
  assert.ok(start !== -1, `locale ${locale} must exist in i18n.tsx`)
  let depth = 0
  let index = source.indexOf('{', start)
  const open = index
  for (; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    else if (source[index] === '}') {
      depth -= 1
      if (depth === 0) break
    }
  }
  const body = source.slice(open, index)
  return [...body.matchAll(/:\s*'((?:[^'\\]|\\.)*)'/g)].map((match) => match[1])
}

function localeKeys(locale) {
  const key = locale === 'en' ? 'en' : `'${locale}'`
  const start = source.indexOf(`\n  ${key}: {`)
  let depth = 0
  let index = source.indexOf('{', start)
  const open = index
  for (; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    else if (source[index] === '}') {
      depth -= 1
      if (depth === 0) break
    }
  }
  const body = source.slice(open, index)
  return new Set([...body.matchAll(/(?:^|[{,]\s*)([a-zA-Z][a-zA-Z0-9]*)\s*:/gm)].map((m) => m[1]))
}

const LOCALES = ['en', 'zh-Hans', 'zh-Hant-HK']

// Unambiguous written-Cantonese markers. Deliberately excludes 係 (ordinary in
// 關係 / 係數), 他 and 不 (ordinary in both varieties) — a noisy check gets
// muted, and a muted check guards nothing.
const CANTONESE = ['嘅', '唔', '喺', '冇', '咗', '睇', '佢', '嗰', '啱', '乜嘢', '畀']

// Script pairs: the Simplified form must not appear in a Traditional locale and
// vice versa. Only characters that genuinely differ across the two scripts.
const SIMPLIFIED_ONLY = ['数', '质', '资', '证', '际', '价', '过', '执', '结', '实', '开', '关', '这', '个', '习']
const TRADITIONAL_ONLY = ['數', '質', '資', '證', '際', '價', '過', '執', '結', '實', '開', '關', '這', '個', '習']

test('every locale has exactly the same keys as English', () => {
  const english = localeKeys('en')
  for (const locale of LOCALES.slice(1)) {
    const keys = localeKeys(locale)
    const missing = [...english].filter((key) => !keys.has(key))
    const extra = [...keys].filter((key) => !english.has(key))
    assert.deepEqual(missing, [], `${locale} is missing keys`)
    assert.deepEqual(extra, [], `${locale} has keys English does not`)
  }
})

test('no Cantonese remains in any locale', () => {
  // The removed zh-HK locale was written Cantonese. zh-Hant-HK is formal
  // written Hong Kong Chinese (書面語) and must stay formal.
  for (const locale of LOCALES) {
    const joined = localeStrings(locale).join(' ')
    const found = CANTONESE.filter((marker) => joined.includes(marker))
    assert.deepEqual(found, [], `${locale} contains Cantonese markers: ${found.join(', ')}`)
  }
})

test('zh-Hans uses Simplified script only', () => {
  const joined = localeStrings('zh-Hans').join(' ')
  const wrong = TRADITIONAL_ONLY.filter((char) => joined.includes(char))
  assert.deepEqual(wrong, [], `zh-Hans contains Traditional characters: ${wrong.join(', ')}`)
})

test('zh-Hant-HK uses Traditional script only', () => {
  const joined = localeStrings('zh-Hant-HK').join(' ')
  const wrong = SIMPLIFIED_ONLY.filter((char) => joined.includes(char))
  assert.deepEqual(wrong, [], `zh-Hant-HK contains Simplified characters: ${wrong.join(', ')}`)
})

test('regional vocabulary does not cross over', () => {
  // These are different words, not different glyphs — the exact trap a
  // character converter falls into.
  const hans = localeStrings('zh-Hans').join(' ')
  const hant = localeStrings('zh-Hant-HK').join(' ')

  // Hong Kong words that must not appear in the mainland locale.
  for (const word of ['質素', '快取', '市賬率', '沽空', '止蝕', '費波那契']) {
    assert.ok(!hans.includes(word), `zh-Hans must not use the Hong Kong word ${word}`)
  }
  // Mainland words that must not appear in the Hong Kong locale.
  for (const word of ['质量', '缓存', '市净率', '卖空', '止损', '斐波那契', '数据']) {
    assert.ok(!hant.includes(word), `zh-Hant-HK must not use the mainland word ${word}`)
  }
})

test('the removed Cantonese locale is really gone', () => {
  assert.ok(!/['"]zh-HK['"]\s*:/.test(source), 'zh-HK locale must not be reintroduced')
  assert.ok(source.includes("stored === 'zh-HK'"), 'stored zh-HK must still migrate to a live locale')
})
