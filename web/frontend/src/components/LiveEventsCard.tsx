import { useEffect, useRef, useState } from 'react'
import { ApiError, checkEventsSession, createEventsSession, friendlyError, getEventsSession } from '../api/client'
import type { EventsSessionStatus, Spec, TraceVocabulary } from '../api/types'
import { usePersistentState } from '../lib/persist'
import { sessionForVocabulary, type SavedLiveSession } from '../lib/liveSession'
import type { Run } from '../lib/run'
import { CopyField } from './AgentConnectCard'

interface Props {
  spec: Spec
  vocabulary: TraceVocabulary
  onRun: (run: Run) => void
  onSeeResults: () => void
}

function remainingTime(expiresAt: string): number {
  return Math.max(0, Date.parse(expiresAt) - Date.now())
}

function isMissing(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.code === 'session_not_found')
}

/** The event session is created here, when Test opens, so its 30 minute TTL is useful. */
export function LiveEventsCard({ spec, vocabulary, onRun, onSeeResults }: Props) {
  const vocabularyKey = JSON.stringify(vocabulary)
  const [saved, setSaved] = usePersistentState<SavedLiveSession | null>('live.session', null)
  const session = sessionForVocabulary(saved, vocabularyKey)
  const [status, setStatus] = useState<EventsSessionStatus | null>(null)
  const [remaining, setRemaining] = useState(() => session ? remainingTime(session.expires_at) : 0)
  const [notFound, setNotFound] = useState(false)
  const [busy, setBusy] = useState<'create' | 'check' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const autoStartedKey = useRef<string | null>(null)
  const expired = !!session && (notFound || remaining === 0)

  async function create() {
    setBusy('create')
    setError(null)
    try {
      const next = await createEventsSession(vocabulary)
      setSaved({ vocabularyKey, session: next })
      setStatus(null)
      setNotFound(false)
      setRemaining(remainingTime(next.expires_at))
    } catch (caught) {
      setError(friendlyError(caught))
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    if (!session && autoStartedKey.current !== vocabularyKey) {
      autoStartedKey.current = vocabularyKey
      if (saved) setSaved(null)
      void create()
    }
  })

  useEffect(() => {
    if (!session || notFound) return
    const tick = () => setRemaining(remainingTime(session.expires_at))
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [session, notFound])

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
          if (isMissing(caught)) setNotFound(true)
          else setError(friendlyError(caught))
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
  }, [session, expired])

  async function check() {
    if (!session || expired || busy) return
    setBusy('check')
    setError(null)
    try {
      const response = await checkEventsSession(session.session_id, spec)
      onRun({ source: { kind: 'live', sessionId: session.session_id, eventCount: response.events.length }, response })
      onSeeResults()
    } catch (caught) {
      if (isMissing(caught)) setNotFound(true)
      else setError(friendlyError(caught))
    } finally {
      setBusy(null)
    }
  }

  const entityArgument = /^[A-Za-z_][A-Za-z0-9_]*$/.test(vocabulary.fields[0])
    ? `${vocabulary.fields[0]}="A-1"`
    : `**{${JSON.stringify(vocabulary.fields[0])}: "A-1"}`
  const python = session
    ? `# copy examples/report_events.py into your project\nfrom report_events import Reporter\nr = Reporter(${JSON.stringify(session.ingest_url)})\nr.emit(${JSON.stringify(vocabulary.events[0])}, ${entityArgument})`
    : ''

  return (
    <section className="card agent-connect" aria-labelledby="live-events-title">
      <h2 id="live-events-title" className="card__title">Connect my agent</h2>
      <p className="card__lead">Send your agent’s events here and check them against your confirmed rules.</p>
      {!session && !error && <p className="notice notice--loading" role="status">{busy === 'create' ? 'Creating your live session…' : 'Preparing your live session…'}</p>}
      {!session && busy !== 'create' && error && <button type="button" className="btn btn--primary" onClick={() => void create()}>Try again</button>}
      {session && expired && (
        <>
          <p className="notice notice--error" role="alert">{friendlyError(new ApiError('Session not found or expired', 404, { code: 'session_not_found' }))}</p>
          <button type="button" className="btn btn--primary" disabled={busy !== null} onClick={() => void create()}>{busy === 'create' ? 'Creating…' : 'Start a new session'}</button>
        </>
      )}
      {session && !expired && (
        <>
          <CopyField label="Ingest URL" value={session.ingest_url} />
          <p className="card__lead">Keep this URL private. Send <code>ts</code> as an ISO 8601 UTC time for time-based rules; without <code>ts</code>, the server uses arrival time.</p>
          <details className="agent-details" open>
            <summary>Python example</summary>
            <CopyField label="Copy this snippet" value={python} />
          </details>
          <details className="agent-details">
            <summary>curl example</summary>
            <p>Replace the sample event and fields with the names you listed.</p>
            <CopyField label="Copy this command" value={session.snippet} />
          </details>
          <p className="agent-expiry">Expires in {Math.floor(Math.ceil(remaining / 1000) / 60)}:{String(Math.ceil(remaining / 1000) % 60).padStart(2, '0')}</p>
          <div className="agent-activity">
            <h3>Live activity</h3>
            {status?.events.length ? (
              <ol>
                {status.events.map((event, index) => (
                  <li key={`${event.ts}:${index}`} className="agent-call">
                    <time dateTime={event.ts}>{new Date(event.ts).toISOString()}</time>
                    <strong>{event.event}</strong>
                    <span className="agent-call__args">{Object.entries(event.data).map(([name, value]) => <code key={name} className="agent-call__chip">{name}={String(value)}</code>)}</span>
                  </li>
                ))}
              </ol>
            ) : <p className="muted">Waiting for events from your agent…</p>}
          </div>
          <div className="card__actions">
            <button type="button" className="btn btn--primary" disabled={busy !== null} onClick={() => void check()}>{busy === 'check' ? 'Checking…' : 'Check now'}</button>
            <button type="button" className="btn btn--link" disabled={busy !== null} onClick={() => void create()}>Start a new session</button>
          </div>
        </>
      )}
      {error && <p className="notice notice--error" role="alert">{error}</p>}
    </section>
  )
}
