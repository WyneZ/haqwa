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

/** One label per event; repeats say "again", field values go in brackets. */
export function timelineLabels(timeline: TimelineEvent[]): string[] {
  const seen = new Map<string, number>()
  return timeline.map(({ event, data }) => {
    const count = (seen.get(event) ?? 0) + 1
    seen.set(event, count)
    const values = Object.values(data).map(String)
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
