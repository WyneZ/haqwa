/**
 * Turn rule/event names into plain words for a non-technical policy owner.
 * Presentation only: no rule logic lives here.
 */
import type { Rule, RuleException, TimelineEvent } from '../api/types'

/** "refund_requested" -> "Refund requested" */
export function humanize(name: string): string {
  const words = name.replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * "P2DT17H" -> "+65h", "P1DT1H" -> "+25h", "PT1H30M" -> "+1h30m"; under a minute, "PT0S"
 * or no offset -> "".
 * Same short form as core's `fmt_duration`, so cards and core messages read alike.
 */
export function offsetText(at?: string): string {
  if (!at) return ''
  const m = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)(?:\.\d+)?S)?)?$/.exec(at)
  if (!m) return ''
  const [d, h, min] = m.slice(1).map((v) => Number(v ?? 0))
  const hours = d * 24 + h
  // Under a minute only orders the events (core uses +1s); it is not a time to decide on.
  const text = `${hours ? `${hours}h` : ''}${min ? `${min}m` : ''}`
  return text ? `+${text}` : ''
}

/**
 * The entities (e.g. orders) in one timeline, in order of first appearance.
 * An event without `data[per]` belongs to the main entity (core's canonical examples
 * only set `data[per]` on the "different entity" event).
 */
function entityKeys(timeline: TimelineEvent[], per?: string): string[] {
  const keys: string[] = []
  for (const { data } of timeline) {
    const key = per && data[per] !== undefined ? String(data[per]) : ''
    if (!keys.includes(key)) keys.push(key)
  }
  return keys
}

/** How many different entities (e.g. orders) a timeline talks about. */
export function entityCount(timeline: TimelineEvent[], per?: string): number {
  return per ? entityKeys(timeline, per).length : 1
}

/**
 * One label per event; repeats say "again", other field values go in brackets, and a
 * time offset from core (`at`) is shown as "+25h" so cards that differ only in time
 * look different.
 *
 * With `per` (the rule's entity key) and more than one entity, each label names its
 * entity as a letter ("Charged (order A)", "Charged (order B)") instead of showing the
 * raw id, and "again" only counts repeats for the same entity.
 *
 * `repeats: false` never says "again": for lists that mix entities without a `per`
 * (an uploaded log), where a repeated event name may belong to someone else.
 */
export function timelineLabels(
  timeline: TimelineEvent[],
  per?: string,
  { repeats = true }: { repeats?: boolean } = {},
): string[] {
  const keys = entityKeys(timeline, per)
  const many = per !== undefined && keys.length > 1
  const noun = per ? entityNoun(per) : ''
  const seen = new Map<string, number>()
  return timeline.map((item) => {
    const { event, data } = item
    const key = per && data[per] !== undefined ? String(data[per]) : ''
    const countKey = many ? `${key}\u0000${event}` : event
    const count = (seen.get(countKey) ?? 0) + 1
    seen.set(countKey, count)
    const values = Object.entries(data)
      .filter(([field]) => !(many && field === per))
      .map(([, value]) => String(value))
    if (many) values.push(`${noun} ${String.fromCharCode(65 + keys.indexOf(key))}`)
    const extra = values.length ? ` (${values.join(', ')})` : ''
    const offset = offsetText(item.at)
    const again = repeats && count > 1 ? ' again' : ''
    return `${humanize(event)}${again}${extra}${offset ? ` ${offset}` : ''}`
  })
}

/**
 * Core's violation message in plain words, e.g.
 * "'leave_decided' happened 49h after 'leave_requested' (limit 48h)"
 * -> "Leave decided happened 49h after leave requested (limit 48h)."
 * Only quotes and underscores change; numbers and wording stay exactly as core wrote them,
 * so an unknown message format still shows correctly (just less polished).
 */
export function checkerFact(message: string): string {
  const words = message.replace(/'([^']*)'/g, '$1').replace(/_/g, ' ').trim()
  if (!words) return ''
  const sentence = words.charAt(0).toUpperCase() + words.slice(1)
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/**
 * Event times for a timeline, e.g. "29 Sep 09:00 UTC", or null when they would not help:
 * all events within one minute (the demo shop uses one timestamp, so order is what
 * matters) or a timestamp that does not parse. Always UTC, so every viewer sees the same
 * time as the checker and the AI text.
 */
export function eventTimes(timeline: { ts: string }[]): string[] | null {
  const times = timeline.map((e) => new Date(e.ts))
  if (times.length === 0 || times.some((d) => Number.isNaN(d.getTime()))) return null
  const ms = times.map((d) => d.getTime())
  if (Math.max(...ms) - Math.min(...ms) < 60_000) return null
  const two = (n: number) => String(n).padStart(2, '0')
  return times.map((d) => {
    const clock = `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${clock} UTC`
  })
}

/** "order_id" -> "order" (used in "If this happens to one order:"). */
export function entityNoun(per: string): string {
  return per.replace(/_id$/, '').replace(/_/g, ' ') || 'item'
}

/** Short title for the rule list, e.g. "No double charge" -> falls back to the id. */
export function ruleTitle(rule: Pick<Rule, 'id'>): string {
  return humanize(rule.id.replace(/-/g, ' '))
}

/** Technical one-liner for an exception, shown only under "Show technical details". */
export function exceptionText(e: RuleException): string {
  if ('reset_after' in e) return `reset_after: ${e.reset_after}`
  const { field, op, value } = e.allow_if
  return `allow_if: ${field} ${op} ${Array.isArray(value) ? value.join(', ') : String(value)}`
}
