import type { EventsSession } from '../api/types'

export interface SavedLiveSession {
  vocabularyKey: string
  session: EventsSession
}

/** Only reuse an endpoint that was created for the current event vocabulary. */
export function sessionForVocabulary(saved: SavedLiveSession | null, vocabularyKey: string): EventsSession | null {
  return saved?.vocabularyKey === vocabularyKey ? saved.session : null
}
