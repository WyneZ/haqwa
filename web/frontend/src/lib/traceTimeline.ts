import type { LogEvent, RunResponse } from '../api/types'

/** Keep only events present in violating timelines, in their original log order. */
export function traceTimeline(response: RunResponse, limit = 200): LogEvent[] {
  const wanted = new Map<string, number>()
  for (const violation of response.report.results.flatMap((result) => result.violations)) {
    const inTimeline = new Map<string, number>()
    for (const event of violation.timeline) {
      const key = JSON.stringify(event)
      inTimeline.set(key, (inTimeline.get(key) ?? 0) + 1)
    }
    for (const [key, count] of inTimeline) {
      wanted.set(key, Math.max(wanted.get(key) ?? 0, count))
    }
  }
  const shown: LogEvent[] = []
  for (const event of response.events) {
    const key = JSON.stringify(event)
    const remaining = wanted.get(key) ?? 0
    if (remaining > 0) {
      shown.push(event)
      wanted.set(key, remaining - 1)
    }
  }
  return shown.slice(-limit)
}
