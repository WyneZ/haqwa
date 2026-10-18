import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  checkAgentSession,
  createAgentSession,
  friendlyError,
  getAgentSession,
} from '../api/client'
import type { AgentFault, AgentSession, AgentSessionStatus, Spec } from '../api/types'
import { usePersistentState } from '../lib/persist'
import type { Run } from '../lib/run'

interface Props {
  spec: Spec
  onRun: (run: Run) => void
}

const REQUIREMENTS = [
  'Your agent needs an MCP client that supports Streamable HTTP. Stdio-only clients need a bridge such as mcp-remote.',
  'Your agent must act through the shop tools Haqwa provides. Other actions are not checked.',
  'Give your agent the task shown here. It uses order A-1; the stale fault affects only A-1.',
  'Do not tell your agent which fault is injected, or the test proves nothing.',
  'Check against shop rules using the shop vocabulary.',
  'Sessions last 30 minutes and allow 200 tool calls. Each IP can create 5 sessions per minute.',
  'The URL is a secret: anyone with it can use the session. Sessions live in memory and are lost on redeploy.',
  'Your agent’s model and cost are yours; Haqwa makes no LLM call for this.',
  'Use test data only, never real customer data.',
  'Time-based rules (within N hours) are not tested in live sessions because the shop clock does not advance.',
]

export function CopyField({ label, value }: { label: string; value: string }) {
  const content = useRef<HTMLElement>(null)
  const [copyState, setCopyState] = useState('Copy')

  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(value)
      setCopyState('Copied')
    } catch {
      if (!content.current) return
      const selection = window.getSelection()
      const range = document.createRange()
      range.selectNodeContents(content.current)
      selection?.removeAllRanges()
      selection?.addRange(range)
      setCopyState('Selected — copy with ⌘/Ctrl+C')
    }
  }

  return (
    <div className="agent-copy">
      <div className="agent-copy__heading">
        <strong>{label}</strong>
        <button type="button" className="btn btn--ghost" onClick={() => void copy()}>
          {copyState}
        </button>
      </div>
      <code ref={content} className="agent-copy__value">{value}</code>
    </div>
  )
}

function remainingTime(expiresAt: string): number {
  return Math.max(0, Date.parse(expiresAt) - Date.now())
}

function countdown(ms: number): string {
  const seconds = Math.ceil(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function argumentText(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export function AgentConnectCard({ spec, onRun }: Props) {
  const [fault, setFault] = useState<AgentFault>('timeout_after_commit')
  const [session, setSession] = usePersistentState<AgentSession | null>('agent.session', null)
  const [status, setStatus] = useState<AgentSessionStatus | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [remaining, setRemaining] = useState(() => session ? remainingTime(session.expires_at) : 0)
  const [busy, setBusy] = useState<'create' | 'check' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const expired = !!session && (notFound || remaining === 0)

  useEffect(() => {
    if (!session || notFound) return
    const tick = () => setRemaining(remainingTime(session.expires_at))
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [session, notFound])

  useEffect(() => {
    if (!session || expired) return
    let mounted = true
    let inFlight = false
    const poll = async () => {
      if (inFlight || !mounted) return
      inFlight = true
      try {
        const next = await getAgentSession(session.session_id)
        if (mounted) {
          setStatus(next)
          setError(null)
        }
      } catch (caught) {
        if (mounted) {
          if (caught instanceof ApiError && (caught.status === 404 || caught.code === 'session_not_found')) {
            setNotFound(true)
          } else {
            setError(friendlyError(caught))
          }
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

  async function create() {
    setBusy('create')
    setError(null)
    try {
      const next = await createAgentSession(fault)
      setStatus(null)
      setNotFound(false)
      setRemaining(remainingTime(next.expires_at))
      setSession(next)
    } catch (caught) {
      setError(friendlyError(caught))
    } finally {
      setBusy(null)
    }
  }

  async function check() {
    if (!session || expired || busy !== null) return
    setBusy('check')
    setError(null)
    try {
      const response = await checkAgentSession(session.session_id, spec)
      onRun({
        source: { kind: 'agent', sessionId: session.session_id, fault: session.fault, callCount: status?.calls.length ?? 0 },
        response,
      })
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 404 || caught.code === 'session_not_found')) {
        setNotFound(true)
      } else {
        setError(friendlyError(caught))
      }
    } finally {
      setBusy(null)
    }
  }

  function reset() {
    setSession(null)
    setStatus(null)
    setNotFound(false)
    setError(null)
  }

  const config = session
    ? JSON.stringify({ mcpServers: { 'haqwa-shop': { transport: 'streamable-http', url: session.mcp_url } } }, null, 2)
    : ''
  const command = session
    ? `uv run python examples/connect_agent.py --url "${session.mcp_url}" --task "${session.task}"`
    : ''

  return (
    <section className="card agent-connect" aria-labelledby="agent-connect-title">
      <h2 id="agent-connect-title" className="card__title">Test your own MCP agent in our demo shop</h2>
      <p className="card__lead">
        Runs on your computer with your own model key. Give your MCP agent a private shop with a fault injected. Haqwa records what it does and checks it against your rules.
      </p>

      {!session && (
        <>
          <fieldset className="agent-faults">
            <legend>Choose a fault</legend>
            <label><input type="radio" name="agent-fault" value="timeout_after_commit" checked={fault === 'timeout_after_commit'} onChange={() => setFault('timeout_after_commit')} /> Payment times out after charging</label>
            <label><input type="radio" name="agent-fault" value="stale_state" checked={fault === 'stale_state'} onChange={() => setFault('stale_state')} /> Order status is stale</label>
          </fieldset>
          <div className="card__actions">
            <button type="button" className="btn btn--primary" disabled={busy !== null} onClick={() => void create()}>
              {busy === 'create' ? 'Creating…' : 'Create endpoint'}
            </button>
          </div>
        </>
      )}

      {session && expired && (
        <>
          <p className="notice notice--error" role="alert">
            {friendlyError(new ApiError('Session not found or expired', 404, { code: 'session_not_found' }))}
          </p>
          <div className="card__actions">
            <button type="button" className="btn btn--primary" onClick={reset}>Create a new endpoint</button>
          </div>
        </>
      )}

      {session && !expired && (
        <>
          <CopyField label="MCP URL" value={session.mcp_url} />
          <CopyField label="Task for your agent" value={session.task} />
          <details className="agent-details">
            <summary>Run our example Gemini agent</summary>
            <CopyField label="Command" value={command} />
          </details>
          <details className="agent-details">
            <summary>Generic MCP client config</summary>
            <CopyField label="JSON" value={config} />
          </details>
          <details className="agent-details" open>
            <summary>Before you connect</summary>
            <ol>{REQUIREMENTS.map((item) => <li key={item}>{item}</li>)}</ol>
          </details>
          <p className="agent-expiry">Expires in {countdown(remaining)}</p>
          <div className="agent-activity">
            <h3>Live activity</h3>
            {status?.calls.length ? (
              <ol>
                {status.calls.map((call, index) => (
                  <li key={`${call.at}:${index}`} className="agent-call">
                    <time dateTime={call.at}>{new Date(call.at).toLocaleTimeString('en-GB', { hour12: false })}</time>
                    <strong>{call.tool}</strong>
                    <span className="agent-call__args">
                      {Object.entries(call.arguments).map(([key, value]) => (
                        <code key={key} className="agent-call__chip">{key}={argumentText(value)}</code>
                      ))}
                    </span>
                    <span className={`agent-call__status ${call.ok ? 'agent-call__status--ok' : 'agent-call__status--error'}`}>
                      {call.ok ? 'ok' : call.error ?? 'error'}
                    </span>
                  </li>
                ))}
              </ol>
            ) : <p className="muted">Waiting for your agent to call a tool…</p>}
          </div>
          <div className="card__actions">
            <button type="button" className="btn btn--primary" disabled={busy !== null} onClick={() => void check()}>
              {busy === 'check' ? 'Checking…' : 'Check now'}
            </button>
            <button type="button" className="btn btn--link" onClick={reset}>Start a new session</button>
          </div>
        </>
      )}
      {error && <p className="notice notice--error" role="alert">{error}</p>}
    </section>
  )
}
