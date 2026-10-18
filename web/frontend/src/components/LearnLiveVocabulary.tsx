import { useEffect, useRef, useState } from 'react'
import { ApiError, createEventsSession, friendlyError, getEventsSession } from '../api/client'
import type { EventsSession, EventsSessionStatus, TraceVocabulary } from '../api/types'
import { seenNames, vocabularyFromSeen } from '../lib/discoveredVocabulary'
import { usePersistentState } from '../lib/persist'
import { CopyField } from './AgentConnectCard'

interface Props {
  onUse: (vocabulary: TraceVocabulary, session: EventsSession) => void
}

export function LearnLiveVocabulary({ onUse }: Props) {
  const [session, setSession] = usePersistentState<EventsSession | null>('evidence.learningSession', null)
  const [status, setStatus] = useState<EventsSessionStatus | null>(null)
  const [entity, setEntity] = usePersistentState('evidence.learn.entity', 'order_id')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)
  const [now, setNow] = useState(0)
  const expired = !!session && Date.parse(session.expires_at) <= now
  const names = seenNames(status?.events ?? [])
  const selectedEntity = names.fields.includes(entity) ? entity : names.fields.includes('order_id') ? 'order_id' : names.fields[0] ?? ''

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const next = await createEventsSession()
      setSession(next)
      setStatus(null)
      setNow(Date.now())
    } catch (caught) {
      setError(friendlyError(caught))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!session && !started.current) {
      started.current = true
      void create()
    }
  })

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!session || expired) return
    let mounted = true
    let inFlight = false
    const poll = async () => {
      if (!mounted || inFlight) return
      inFlight = true
      try {
        const next = await getEventsSession(session.session_id)
        if (mounted) {
          setStatus(next)
          setError(null)
        }
      } catch (caught) {
        if (mounted) {
          if (caught instanceof ApiError && (caught.status === 404 || caught.code === 'session_not_found')) {
            setSession(null)
            setStatus(null)
            setError('Session expired. Start a new session to learn names.')
          } else setError(friendlyError(caught))
        }
      } finally {
        inFlight = false
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 2000)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [session, expired, setSession])

  function useNames() {
    if (!session || expired) return
    try {
      onUse(vocabularyFromSeen(names, selectedEntity), session)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Check the names and try again.')
    }
  }

  const sampleEvent = names.events[0] ?? 'order_approved'
  const sampleEntity = selectedEntity || 'order_id'
  const python = session
    ? `# copy examples/report_events.py into your project\nfrom report_events import Reporter\nr = Reporter(${JSON.stringify(session.ingest_url)})\nr.emit(${JSON.stringify(sampleEvent)}, **{${JSON.stringify(sampleEntity)}: "A-1"})`
    : ''

  return (
    <section className="learn-live" aria-label="Learn the names from my agent">
      <p>Send a few example events from your agent. We’ll list the event names and fields it reports.</p>
      {!session && !error && <p className="notice notice--loading" role="status">Creating your live session…</p>}
      {session && !expired && (
        <>
          <CopyField label="Ingest URL" value={session.ingest_url} />
          <p className="card__lead">Keep this URL private. Send <code>ts</code> as an ISO 8601 UTC time for time-based rules; without it, the server uses arrival time.</p>
          <details className="agent-details" open>
            <summary>Python example</summary>
            <CopyField label="Copy this snippet" value={python} />
          </details>
          <details className="agent-details">
            <summary>curl example</summary>
            <CopyField label="Copy this command" value={session.snippet} />
          </details>
          <p className="agent-expiry">Session expires at {new Date(session.expires_at).toLocaleTimeString()}.</p>
          <h3>Names seen so far</h3>
          {names.events.length ? (
            <>
              <p>Event names</p>
              <ul className="name-chips" aria-label="Seen event names">{names.events.map((name) => <li className="name-chip" key={name}>{name}</li>)}</ul>
              <p>Fields in <code>data</code></p>
              <ul className="name-chips" aria-label="Seen fields">{names.fields.map((name) => <li className="name-chip" key={name}>{name}{names.numericFields.includes(name) && <span className="muted"> · numeric</span>}</li>)}</ul>
            </>
          ) : <p className="muted">Waiting for events from your agent…</p>}
          {names.fields.length > 0 && (
            <>
              <label htmlFor="learn-entity-field">Entity field</label>
              <select id="learn-entity-field" value={selectedEntity} onChange={(event) => setEntity(event.target.value)}>
                {names.fields.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <p className="card__lead">Events for the same entity share this field in <code>data</code>.</p>
            </>
          )}
          <button type="button" className="btn btn--primary" disabled={!names.events.length || !names.fields.length} onClick={useNames}>Use these names →</button>
        </>
      )}
      {(expired || (!session && error)) && <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => void create()}>{busy ? 'Creating…' : 'Start a new session'}</button>}
      {error && <p className="notice notice--error" role="alert">{error}</p>}
    </section>
  )
}
