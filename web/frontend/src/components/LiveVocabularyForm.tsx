import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { friendlyError, suggestVocabulary } from '../api/client'
import type { SuggestedEvent, TraceVocabulary } from '../api/types'
import { buildLiveVocabulary, NAME, type LiveField } from '../lib/liveVocabulary'
import { usePersistentState } from '../lib/persist'

interface Props {
  policy: string
  onUse: (vocabulary: TraceVocabulary, suggestedEvents?: SuggestedEvent[]) => void
}

/** Names the agent will report; no session is created until the Test stage. */
export function LiveVocabularyForm({ policy, onUse }: Props) {
  const [events, setEvents] = usePersistentState<string[]>('evidence.live.events', [])
  const [entity, setEntity] = usePersistentState('evidence.live.entity', '')
  const [fields, setFields] = usePersistentState<LiveField[]>('evidence.live.fields', [])
  const [eventInput, setEventInput] = useState('')
  const [fieldInput, setFieldInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const missingRequired = entity.trim() === ''
    || (events.length === 0 && !eventInput.split(',').some((name) => name.trim() !== ''))
  const [suggesting, setSuggesting] = useState(false)
  const [suggested, setSuggested] = useState<SuggestedEvent[] | null>(null)

  async function suggest() {
    setSuggesting(true)
    setError(null)
    try {
      const result = await suggestVocabulary(policy)
      setEvents(result.events.map((event) => event.name))
      setEntity(result.entity_field)
      setFields(result.fields.filter((field) => field !== result.entity_field).map((name) => ({ name, numeric: false })))
      setSuggested(result.events)
      setEventInput('')
      setFieldInput('')
    } catch (cause) {
      setError(friendlyError(cause))
    } finally {
      setSuggesting(false)
    }
  }

  function addEvents() {
    const names = eventInput.split(',').map((name) => name.trim()).filter(Boolean)
    if (names.length === 0) return
    const next = [...events, ...names]
    if (next.length > 100) setError('Use at most 100 event names.')
    else if (next.some((name) => !NAME.test(name))) setError('Event names must start with a letter and use letters, numbers, _, . or -.')
    else if (new Set(next).size !== next.length) setError('Event names must be unique.')
    else {
      setEvents(next)
      setEventInput('')
      setError(null)
    }
  }

  function addField() {
    const name = fieldInput.trim()
    if (!name) return
    if (!NAME.test(name)) {
      setError('Field names must start with a letter and use letters, numbers, _, . or -.')
      return
    }
    if (name === entity.trim() || fields.some((field) => field.name === name)) {
      setError('Field names must be unique.')
      return
    }
    if (fields.length >= 99) {
      setError('Use at most 100 fields.')
      return
    }
    setFields([...fields, { name, numeric: false }])
    setFieldInput('')
    setError(null)
  }

  function onEnter(event: KeyboardEvent<HTMLInputElement>, add: () => void) {
    if (event.key === 'Enter') {
      event.preventDefault()
      add()
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      const pending = eventInput.split(',').map((name) => name.trim()).filter(Boolean)
      const pendingField = fieldInput.trim()
      const nextFields = pendingField ? [...fields, { name: pendingField, numeric: false }] : fields
      const vocabulary = buildLiveVocabulary([...events, ...pending], entity, nextFields)
      if (pending.length) {
        setEvents(vocabulary.events)
        setEventInput('')
      }
      if (pendingField) {
        setFields(nextFields)
        setFieldInput('')
      }
      setError(null)
      onUse(vocabulary, suggested?.filter((item) => vocabulary.events.includes(item.name)))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Check the names and try again.')
    }
  }

  return (
    <form className="live-vocabulary" onSubmit={submit}>
      <p>Name the case field and events your agent will report.</p>
      <button type="button" className="btn btn--ghost" disabled={suggesting} onClick={() => void suggest()}>
        {suggesting ? 'Suggesting…' : 'Suggest from my policy'}
      </button>
      {suggested && <p className="card__lead">Suggestions filled the form. Edit any name or field before continuing.</p>}
      <div className="live-vocabulary__group">
        <label htmlFor="live-entity-field">Which field identifies one case? <span className="field-required" aria-hidden="true">*</span></label>
        <input
          id="live-entity-field"
          value={entity}
          onChange={(event) => setEntity(event.target.value)}
          placeholder="e.g. order_id"
          aria-describedby="live-entity-hint"
          required
        />
        <p id="live-entity-hint" className="card__lead">Events about the same case (for example one order) share this field.</p>
      </div>
      <div className="live-vocabulary__group">
        <label htmlFor="live-event-name">Event names (at least one) <span className="field-required" aria-hidden="true">*</span></label>
        <div className="live-vocabulary__entry">
          <input
            id="live-event-name"
            value={eventInput}
            onChange={(event) => setEventInput(event.target.value)}
            onKeyDown={(event) => onEnter(event, addEvents)}
            placeholder="e.g. order_approved"
            aria-describedby="live-event-hint"
            required={events.length === 0}
          />
          <button type="button" className="btn btn--ghost" onClick={addEvents}>Add event</button>
        </div>
        <p id="live-event-hint" className="card__lead">Separate several names with commas, or press Enter.</p>
        {events.length > 0 && (
          <ul className="name-chips" aria-label="Event names">
            {events.map((name) => (
              <li key={name} className="name-chip">
                {name}
                <button type="button" aria-label={`Remove event ${name}`} onClick={() => setEvents(events.filter((item) => item !== name))}>×</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="live-vocabulary__group">
        <label htmlFor="live-other-field">Other fields (optional)</label>
        <div className="live-vocabulary__entry">
          <input
            id="live-other-field"
            value={fieldInput}
            onChange={(event) => setFieldInput(event.target.value)}
            onKeyDown={(event) => onEnter(event, addField)}
            placeholder="e.g. amount"
          />
          <button type="button" className="btn btn--ghost" onClick={addField}>Add field</button>
        </div>
        {fields.length > 0 && (
          <ul className="name-chips" aria-label="Other fields">
            {fields.map((field) => (
              <li key={field.name} className="name-chip">
                <span>{field.name}</span>
                <label>
                  <input
                    type="checkbox"
                    checked={field.numeric}
                    onChange={(event) => setFields(fields.map((item) => item.name === field.name ? { ...item, numeric: event.target.checked } : item))}
                  />
                  Numeric
                </label>
                <button type="button" aria-label={`Remove field ${field.name}`} onClick={() => setFields(fields.filter((item) => item.name !== field.name))}>×</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      <button type="submit" className="btn btn--primary" disabled={missingRequired}>Next: understand policy →</button>
    </form>
  )
}
