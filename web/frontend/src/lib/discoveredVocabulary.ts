import type { LogEvent, TraceVocabulary } from '../api/types'
import { buildLiveVocabulary } from './liveVocabulary'

export interface SeenNames {
  events: string[]
  fields: string[]
  numericFields: string[]
}

/** Names come from data keys, never from timestamps or other event metadata. */
export function seenNames(events: LogEvent[]): SeenNames {
  const eventNames = new Set<string>()
  const fieldValues = new Map<string, unknown[]>()
  for (const item of events) {
    eventNames.add(item.event)
    for (const [name, value] of Object.entries(item.data ?? {})) {
      const values = fieldValues.get(name) ?? []
      values.push(value)
      fieldValues.set(name, values)
    }
  }
  const fields = [...fieldValues.keys()].sort()
  return {
    events: [...eventNames].sort(),
    fields,
    numericFields: fields.filter((name) => fieldValues.get(name)!.every((value) => typeof value === 'number' && Number.isFinite(value))),
  }
}

export function vocabularyFromSeen(names: SeenNames, entity: string): TraceVocabulary {
  if (!names.fields.includes(entity)) throw new Error('Choose an entity field from the events received.')
  const vocabulary = buildLiveVocabulary(names.events, entity, names.fields
    .filter((name) => name !== entity)
    .map((name) => ({ name, numeric: names.numericFields.includes(name) })))
  vocabulary.numeric_fields = names.fields.filter((name) => names.numericFields.includes(name))
  return vocabulary
}
