import assert from 'node:assert/strict'
import test, { after } from 'node:test'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'
import { act, createElement } from 'react'
import type { Root } from 'react-dom/client'
import { Window } from 'happy-dom'
import { createServer } from 'vite'
import { DEMO_RESULTS } from '../src/api/fixtures.ts'
import { buildLiveVocabulary } from '../src/lib/liveVocabulary.ts'
import { seenNames, vocabularyFromSeen } from '../src/lib/discoveredVocabulary.ts'
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
  root: fileURLToPath(new URL('..', import.meta.url)),
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
  const buttons = [...browser.document.querySelectorAll('button')]
  const found = buttons.find((item) => item.textContent?.trim() === label)
    ?? buttons.find((item) => item.textContent?.includes(label))
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
  assert.ok(check(), `expected UI state appeared: ${browser.document.body.textContent}`)
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

test('demo selection automatically replaces the policy and switching demos updates it', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url: string) => {
    assert.equal(url, '/samples/hr-events.json')
    return new Response(await readFile(new URL('../public/samples/hr-events.json', import.meta.url), 'utf8'))
  })
  const root = await renderApp()
  try {
    await click('HR leave policy')
    await click('Next: choose evidence')
    await click('Try a demo')
    assert.match(JSON.parse(browser.sessionStorage.getItem(key('define.text'))!), /charged twice/)
    assert.match(browser.document.querySelector('[role="alert"]')?.textContent ?? '', /Online shop/)
    assert.ok(!browser.document.body.textContent?.includes('Use the demo policy'))
    await click('HR')
    await waitFor(() => JSON.parse(browser.sessionStorage.getItem(key('source'))!).kind === 'trace')
    assert.match(JSON.parse(browser.sessionStorage.getItem(key('define.text'))!), /leave request/)
    assert.match(browser.document.querySelector('[role="alert"]')?.textContent ?? '', /HR/)
    await click('← Edit policy')
    const policy = browser.document.getElementById('policy') as HTMLTextAreaElement
    assert.match(policy.value, /leave request/)
    assert.equal(JSON.parse(browser.sessionStorage.getItem(key('evidence.choice'))!), 'demo')
    await click('Online shop policy')
    await click('Next: choose evidence')
    await click('Next: understand policy')
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Meaning')
    assert.match((browser.document.getElementById('policy') as HTMLTextAreaElement).value, /leave request/)
  } finally { await cleanup(root) }
})

test('document review locks policy editing and navigation until Cancel or Use', async () => {
  const root = await renderApp()
  try {
    await click('Online shop policy')
    const policy = browser.document.getElementById('policy') as HTMLTextAreaElement
    const original = policy.value
    const next = button('Next: choose evidence')
    const fileInput = browser.document.querySelector('input[type="file"]') as HTMLInputElement
    async function uploadDocument() {
      await act(async () => {
        Object.defineProperty(fileInput, 'files', {
          configurable: true,
          value: [new browser.File(['Policy document'], 'policy.txt', { type: 'text/plain' })],
        })
        fileInput.dispatchEvent(new browser.Event('change', { bubbles: true }))
      })
      assert.equal(policy.hidden, true)
      assert.equal(next.disabled, true)
      await waitFor(() => !!browser.document.querySelector('[aria-label="Rules found in your document"]'))
    }
    assert.equal(policy.readOnly, false)
    assert.equal(next.disabled, false)
    await uploadDocument()
    assert.equal(policy.readOnly, true)
    assert.equal(policy.hidden, true)
    assert.equal(next.disabled, true)
    assert.ok(button('Replace your text with 3 rules'))
    assert.match(browser.document.querySelector('[aria-live="polite"]')?.textContent ?? '', /Use or cancel/)
    await click('Cancel')
    assert.equal(policy.readOnly, false)
    assert.equal(policy.hidden, false)
    assert.equal(next.disabled, false)
    assert.equal(policy.value, original)
    assert.equal(browser.document.activeElement, policy)
    await uploadDocument()
    await click('Replace your text with 3 rules')
    assert.equal(policy.readOnly, false)
    assert.equal(policy.hidden, false)
    assert.equal(next.disabled, false)
    assert.equal(browser.document.activeElement, policy)
    assert.equal(browser.document.querySelector('.upload__result'), null)
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

test('discovery lists distinct names and marks numeric fields only when every seen value is a number', () => {
  const names = seenNames([
    { event: 'paid', ts: '2026-10-18T00:00:00Z', data: { order_id: 'A-1', amount: 1, retry: false, mixed: 2 } },
    { event: 'paid', ts: '2026-10-18T00:00:01Z', data: { order_id: 'A-2', amount: 1.5, retry: true, mixed: 'x' } },
    { event: 'shipped', ts: '2026-10-18T00:00:02Z', data: { order_id: 'A-2' } },
  ])
  assert.deepEqual(names.events, ['paid', 'shipped'])
  assert.deepEqual(names.fields, ['amount', 'mixed', 'order_id', 'retry'])
  assert.deepEqual(names.numericFields, ['amount'])
  assert.deepEqual(vocabularyFromSeen(names, 'order_id'), {
    events: ['paid', 'shipped'], fields: ['order_id', 'amount', 'mixed', 'retry'], field_values: {}, numeric_fields: ['amount'],
  })
  assert.throws(() => vocabularyFromSeen(names, 'customer_id'), /Choose an entity field/)
})

test('the live evidence form stores its vocabulary and advances to Meaning', async () => {
  const root = await renderApp()
  try {
    await click('Online shop policy')
    await click('Next: choose evidence')
    await click('Connect my agent (live)')
    const entity = browser.document.getElementById('live-entity-field') as HTMLInputElement
    assert.equal(entity.value, '')
    const next = button('Next: understand policy')
    assert.equal(next.disabled, true)
    await input('live-entity-field', 'order_id')
    assert.equal(next.disabled, true)
    await input('live-entity-field', '   ')
    await input('live-event-name', 'order_approved')
    await click('Add event')
    assert.equal(next.disabled, true)
    await input('live-entity-field', 'order_id')
    assert.equal(next.disabled, false)
    await act(async () => {
      (browser.document.querySelector('[aria-label="Remove event order_approved"]') as HTMLButtonElement).click()
    })
    assert.equal(next.disabled, true)
    await input('live-event-name', ', ,')
    assert.equal(next.disabled, true)
    await input('live-event-name', 'order_approved')
    assert.equal(next.disabled, false)
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

test('learning names creates a vocabulary-free session and Test reuses it', async () => {
  const root = await renderApp()
  let saved: { vocabularyKey: string; session: { session_id: string; ingest_url: string } }
  let source: unknown
  try {
    await click('Online shop policy')
    await click('Next: choose evidence')
    await click('Connect my agent (live)')
    await click('Learn the names from my agent')
    await waitFor(() => !!browser.document.querySelector('.agent-copy__value'))
    assert.match(browser.document.body.textContent ?? '', /Python example/)
    assert.match(browser.document.body.textContent ?? '', /curl example/)
    await waitFor(() => !!browser.document.querySelector('[aria-label="Seen event names"]'))
    assert.match(browser.document.body.textContent ?? '', /order_approved/)
    assert.match(browser.document.body.textContent ?? '', /amount · numeric/)
    const entity = browser.document.getElementById('learn-entity-field') as HTMLSelectElement
    assert.equal(entity.value, 'order_id')
    await click('Use these names')
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Meaning')
    saved = JSON.parse(browser.sessionStorage.getItem(key('live.session'))!)
    source = JSON.parse(browser.sessionStorage.getItem(key('source'))!)
    assert.deepEqual((source as { vocabulary: { numeric_fields: string[] } }).vocabulary.numeric_fields, ['amount'])
    assert.equal(saved.vocabularyKey, JSON.stringify((source as { vocabulary: unknown }).vocabulary))
  } finally { await cleanup(root) }

  browser.sessionStorage.setItem(key('live.session'), JSON.stringify(saved!))
  browser.sessionStorage.setItem(key('source'), JSON.stringify(source))
  browser.sessionStorage.setItem(key('step'), JSON.stringify('test'))
  browser.sessionStorage.setItem(key('spec'), JSON.stringify({ version: 2, rules: DEMO_RESULTS.filter((item) => item.status === 'supported').map((item) => toSpecRule(item.rule, [])) }))
  browser.sessionStorage.setItem(key('specYaml'), JSON.stringify('version: 2'))
  const testRoot = await renderApp()
  try {
    await waitFor(() => browser.document.body.textContent?.includes(saved!.session.ingest_url) ?? false)
    assert.equal(JSON.parse(browser.sessionStorage.getItem(key('live.session'))!).session.session_id, saved!.session.session_id)
    await click('Check now')
    assert.equal(browser.document.querySelector('[aria-current="step"] .step__label')?.textContent, 'Results')
  } finally { await cleanup(testRoot) }
})

test('policy suggestions fill editable live event and field names', async () => {
  const root = await renderApp()
  try {
    await click('Online shop policy')
    await click('Next: choose evidence')
    await click('Connect my agent (live)')
    await click('Suggest from my policy')
    await waitFor(() => !!browser.document.body.textContent?.includes('order_charged'))
    assert.equal((browser.document.getElementById('live-entity-field') as HTMLInputElement).value, 'order_id')
    await input('live-entity-field', 'purchase_id')
    await click('Next: understand policy')
    const source = JSON.parse(browser.sessionStorage.getItem(key('source'))!)
    assert.deepEqual(source.vocabulary.events, ['order_charged', 'order_cancelled', 'order_shipped'])
    assert.equal(source.vocabulary.fields[0], 'purchase_id')
    assert.equal(source.suggestedEvents[0].description, 'The order was charged.')
  } finally { await cleanup(root) }
})

test('Test shows the suggested event guide and examples', async () => {
  const vocabulary = buildLiveVocabulary(['order_charged', 'order_shipped'], 'order_id', [])
  browser.sessionStorage.setItem(key('step'), JSON.stringify('test'))
  browser.sessionStorage.setItem(key('source'), JSON.stringify({
    kind: 'live', vocabulary,
    suggestedEvents: [
      { name: 'order_charged', description: 'The order was charged.' },
      { name: 'order_shipped', description: 'The order was shipped.' },
    ],
  }))
  browser.sessionStorage.setItem(key('spec'), JSON.stringify({ version: 2, rules: DEMO_RESULTS.filter((item) => item.status === 'supported').map((item) => toSpecRule(item.rule, [])) }))
  browser.sessionStorage.setItem(key('specYaml'), JSON.stringify('version: 2'))
  const root = await renderApp()
  try {
    await waitFor(() => browser.document.body.textContent?.includes('Copy guide') ?? false)
    assert.match(browser.document.body.textContent ?? '', /The order was charged/)
    assert.match(browser.document.body.textContent ?? '', /reporter\.emit\("order_shipped", order_id="A-1"\)/)
    assert.match(browser.document.body.textContent ?? '', /Copy guide/)
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
