import assert from 'node:assert/strict'
import test, { after } from 'node:test'
import { act, createElement } from 'react'
import type { Root } from 'react-dom/client'
import { Window } from 'happy-dom'
import { createServer } from 'vite'
import { DEMO_RESULTS } from '../src/api/fixtures.ts'
import { buildLiveVocabulary } from '../src/lib/liveVocabulary.ts'
import { sessionForVocabulary } from '../src/lib/liveSession.ts'
import { toSpecRule } from '../src/lib/specRule.ts'

const browser = new Window({ url: 'http://localhost:5173/' })
Object.assign(globalThis, {
  window: browser,
  document: browser.document,
  sessionStorage: browser.sessionStorage,
  HTMLElement: browser.HTMLElement,
  IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: browser.navigator })
const { createRoot } = await import('react-dom/client')

const vite = await createServer({
  root: new URL('..', import.meta.url).pathname,
  configFile: false,
  envFile: false,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'silent',
})
const { default: App } = await vite.ssrLoadModule('/src/App.tsx')
after(async () => { await vite.close(); await browser.happyDOM.abort() })

const key = (name: string) => `haqwa:v5:${name}`

async function renderApp(): Promise<Root> {
  browser.document.body.innerHTML = '<div id="root"></div>'
  const root = createRoot(browser.document.getElementById('root')!)
  await act(async () => { root.render(createElement(App)) })
  return root
}

async function cleanup(root: Root) {
  await act(async () => { root.unmount() })
  browser.sessionStorage.clear()
}

function button(label: string): HTMLButtonElement {
  const found = [...browser.document.querySelectorAll('button')].find((item) => item.textContent?.includes(label))
  assert.ok(found, `button ${label} is visible`)
  return found as HTMLButtonElement
}

async function click(label: string) {
  await act(async () => { button(label).click() })
}

async function input(id: string, value: string) {
  const element = browser.document.getElementById(id) as HTMLInputElement
  assert.ok(element, `input ${id} is visible`)
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(browser.HTMLInputElement.prototype, 'value')?.set
    setter?.call(element, value)
    element.dispatchEvent(new browser.Event('input', { bubbles: true }))
    element.dispatchEvent(new browser.Event('change', { bubbles: true }))
  })
}

async function waitFor(check: () => boolean) {
  for (let attempt = 0; attempt < 50; attempt++) {
    if (check()) return
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
  }
  assert.ok(check(), 'expected UI state appeared')
}

test('header follows Policy, Evidence, Meaning, Test, Results; stale version starts at Policy', async () => {
  browser.sessionStorage.setItem('haqwa:v4:step', JSON.stringify('results'))
  const root = await renderApp()
  try {
    const labels = [...browser.document.querySelectorAll('.step__label')].map((item) => item.textContent)
    assert.deepEqual(labels, ['Policy', 'Evidence', 'Meaning', 'Test', 'Results'])
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Policy')
    assert.ok(browser.document.getElementById('policy'))
  } finally { await cleanup(root) }
})

test('demo policy button fills the policy box and keeps the evidence choice', async () => {
  const root = await renderApp()
  try {
    await click('Online shop policy')
    await click('Next: choose evidence')
    await click('Try a demo')
    await click('Use the demo policy')
    const policy = browser.document.getElementById('policy') as HTMLTextAreaElement
    assert.match(policy.value, /charged twice/)
    assert.equal(JSON.parse(browser.sessionStorage.getItem(key('evidence.choice'))!), 'demo')
  } finally { await cleanup(root) }
})

test('live vocabulary validates names, duplicates and numeric fields', () => {
  assert.throws(() => buildLiveVocabulary(['9bad'], 'order_id', []), /Event names/)
  assert.throws(() => buildLiveVocabulary(['done', 'done'], 'order_id', []), /unique/)
  assert.throws(() => buildLiveVocabulary(['done'], 'order_id', [{ name: 'order_id', numeric: false }]), /unique/)
  assert.throws(() => buildLiveVocabulary(['done'], '9bad', []), /Field names/)
  assert.deepEqual(buildLiveVocabulary(['order_approved'], 'order_id', [{ name: 'amount', numeric: true }]), {
    events: ['order_approved'], fields: ['order_id', 'amount'], field_values: {}, numeric_fields: ['amount'],
  })
})

test('the live evidence form stores its vocabulary and advances to Meaning', async () => {
  const root = await renderApp()
  try {
    await click('Online shop policy')
    await click('Next: choose evidence')
    await click('Connect my agent (live)')
    await input('live-event-name', 'order_approved')
    await click('Add event')
    await input('live-other-field', 'amount')
    await click('Add field')
    const numeric = browser.document.querySelector('.name-chip input[type="checkbox"]') as HTMLInputElement
    assert.ok(numeric, browser.document.body.textContent ?? '')
    await act(async () => { numeric.click() })
    await click('Next: understand policy')
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Meaning')
    const source = JSON.parse(browser.sessionStorage.getItem(key('source'))!)
    assert.equal(source.kind, 'live')
    assert.deepEqual(source.vocabulary.numeric_fields, ['amount'])
  } finally { await cleanup(root) }
})

test('a saved session for another vocabulary is discarded and replaced on Test', async () => {
  const oldVocabulary = buildLiveVocabulary(['old_event'], 'order_id', [])
  const currentVocabulary = buildLiveVocabulary(['order_approved'], 'order_id', [])
  const oldSession = { session_id: 'old-session', kind: 'events', ingest_url: 'https://example.test/old', expires_at: new Date(Date.now() + 60_000).toISOString(), snippet: 'old' } as const
  const saved = { vocabularyKey: JSON.stringify(oldVocabulary), session: oldSession }
  assert.equal(sessionForVocabulary(saved, JSON.stringify(currentVocabulary)), null)
  assert.equal(sessionForVocabulary(saved, JSON.stringify(oldVocabulary)), oldSession)
  browser.sessionStorage.setItem(key('live.session'), JSON.stringify(saved))
  browser.sessionStorage.setItem(key('step'), JSON.stringify('test'))
  browser.sessionStorage.setItem(key('source'), JSON.stringify({ kind: 'live', vocabulary: currentVocabulary }))
  browser.sessionStorage.setItem(key('spec'), JSON.stringify({ version: 2, rules: DEMO_RESULTS.filter((item) => item.status === 'supported').map((item) => toSpecRule(item.rule, [])) }))
  browser.sessionStorage.setItem(key('specYaml'), JSON.stringify('version: 2'))
  const root = await renderApp()
  try {
    assert.equal(browser.sessionStorage.getItem(key('live.session')), 'null')
    await waitFor(() => !!browser.document.querySelector('.agent-copy__value'))
    const next = JSON.parse(browser.sessionStorage.getItem(key('live.session'))!)
    assert.notEqual(next.session.session_id, oldSession.session_id)
    assert.equal(next.vocabularyKey, JSON.stringify(currentVocabulary))
    assert.ok(!browser.document.body.textContent?.includes(oldSession.ingest_url))
    assert.match(browser.document.body.textContent ?? '', /from report_events import Reporter/)
    await click('Check now')
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Results')
    await click('Back to test')
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Test')
    assert.equal(JSON.parse(browser.sessionStorage.getItem(key('live.session'))!).session.session_id, next.session.session_id)
  } finally { await cleanup(root) }
})
