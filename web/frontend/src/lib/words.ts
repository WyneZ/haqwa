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
 * One label per event; repeats say "again", other field values go in brackets.
 *
 * With `per` (the rule's entity key) and more than one entity, each label names its
 * entity as a letter ("Charged (order A)", "Charged (order B)") instead of showing the
 * raw id, and "again" only counts repeats for the same entity.
 */
export function timelineLabels(timeline: TimelineEvent[], per?: string): string[] {
  const keys = entityKeys(timeline, per)
  const many = per !== undefined && keys.length > 1
  const noun = per ? entityNoun(per) : ''
  const seen = new Map<string, number>()
  return timeline.map(({ event, data }) => {
    const key = per && data[per] !== undefined ? String(data[per]) : ''
    const countKey = many ? `${key}\u0000${event}` : event
    const count = (seen.get(countKey) ?? 0) + 1
    seen.set(countKey, count)
    const values = Object.entries(data)
      .filter(([field]) => !(many && field === per))
      .map(([, value]) => String(value))
    if (many) values.push(`${noun} ${String.fromCharCode(65 + keys.indexOf(key))}`)
    const extra = values.length ? ` (${values.join(', ')})` : ''
    return `${humanize(event)}${count > 1 ? ' again' : ''}${extra}`
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
