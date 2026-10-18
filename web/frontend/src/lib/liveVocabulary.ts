import type { TraceVocabulary } from '../api/types'

/** Match VocabularyIn.NAME in the API. */
export const NAME = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/

export interface LiveField {
  name: string
  numeric: boolean
}

export function buildLiveVocabulary(
  eventNames: string[],
  entityField: string,
  optionalFields: LiveField[],
): TraceVocabulary {
  const events = eventNames.map((name) => name.trim())
  const entity = entityField.trim()
  const fields = [entity, ...optionalFields.map((field) => field.name.trim())]
  if (events.length < 1) throw new Error('Add at least one event name.')
  if (events.length > 100 || fields.length > 100) {
    throw new Error('Use at most 100 event names and 100 fields.')
  }
  if (events.some((name) => !NAME.test(name))) {
    throw new Error('Event names must start with a letter and use letters, numbers, _, . or -.')
  }
  if (fields.some((name) => !NAME.test(name))) {
    throw new Error('Field names must start with a letter and use letters, numbers, _, . or -.')
  }
  if (new Set(events).size !== events.length) throw new Error('Event names must be unique.')
  if (new Set(fields).size !== fields.length) throw new Error('Field names must be unique.')
  return {
    events,
    fields,
    field_values: {},
    numeric_fields: optionalFields.filter((field) => field.numeric).map((field) => field.name.trim()),
  }
}
