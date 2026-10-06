/**
 * Keep UI state across a page refresh (decision 2026-10-05: React state + sessionStorage,
 * no router).
 *
 * sessionStorage lives as long as the browser tab: refresh keeps the owner's progress,
 * a new tab starts clean. It holds only policy text, rules and run results, never secrets.
 * Bump VERSION when a saved shape changes, so old saved data is ignored instead of
 * breaking the app.
 */
import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'

const VERSION = 'v1'
const PREFIX = `haqwa:${VERSION}:`

function load<T>(key: string, initial: T): T {
  try {
    const raw = sessionStorage.getItem(PREFIX + key)
    return raw === null ? initial : (JSON.parse(raw) as T)
  } catch {
    return initial // storage blocked (e.g. some private windows) or bad JSON
  }
}

/** Like useState, but the value survives a refresh of this tab. */
export function usePersistentState<T>(
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => load(key, initial))
  useEffect(() => {
    try {
      sessionStorage.setItem(PREFIX + key, JSON.stringify(value))
    } catch {
      // storage blocked or full: keep working in memory only
    }
  }, [key, value])
  return [value, setValue]
}

/** Forget everything Haqwa saved in this tab ("Start over"). */
export function clearSaved(): void {
  try {
    Object.keys(sessionStorage)
      .filter((k) => k.startsWith(PREFIX))
      .forEach((k) => sessionStorage.removeItem(k))
  } catch {
    // nothing saved
  }
}
