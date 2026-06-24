import type { AuditEventOut } from '../types/api'
import { formatDateTime, formatMoney } from '../utils/format'

type AuditTimelineProps = {
  events: AuditEventOut[]
}

function eventTitle(event: AuditEventOut): string {
  switch (event.event_type) {
    case 'claim.submitted':
      return 'Claim submitted'
    case 'line_item.decided':
      return 'Line item decided'
    case 'claim.paid':
      return 'Claim paid'
    case 'line_item.state_changed':
      return 'Line item state changed'
    case 'dispute.filed':
      return 'Dispute filed'
    case 'dispute.resolved':
      return 'Dispute resolved'
    default:
      return event.event_type.replace(/[._]/g, ' ')
  }
}

function eventDetail(event: AuditEventOut): string {
  const p = event.payload

  if (event.event_type === 'claim.submitted') {
    const parts = [
      p.provider_name ? `Provider: ${String(p.provider_name)}` : null,
      p.service_date ? `Service date: ${String(p.service_date)}` : null,
      p.line_item_count != null ? `${String(p.line_item_count)} line item(s)` : null,
    ].filter(Boolean)
    return parts.join(' · ')
  }

  if (event.event_type === 'line_item.decided') {
    const parts = [
      p.outcome ? `Outcome: ${String(p.outcome)}` : null,
      p.previous_status && p.new_status
        ? `${String(p.previous_status)} → ${String(p.new_status)}`
        : null,
      p.payable_amount != null ? `Plan pays ${formatMoney(String(p.payable_amount))}` : null,
      p.member_responsibility != null
        ? `Member pays ${formatMoney(String(p.member_responsibility))}`
        : null,
    ].filter(Boolean)
    return parts.join(' · ')
  }

  const keys = Object.keys(p)
  if (keys.length === 0) return ''
  return keys
    .slice(0, 4)
    .map((k) => `${k}: ${String(p[k])}`)
    .join(' · ')
}

export function AuditTimeline({ events }: AuditTimelineProps) {
  if (events.length === 0) {
    return <p className="empty-note">No audit events recorded.</p>
  }

  return (
    <ol className="audit-timeline">
      {events.map((event) => (
        <li key={event.id} className="audit-event">
          <div className="audit-event__dot" aria-hidden="true" />
          <div className="audit-event__body">
            <div className="audit-event__head">
              <strong>{eventTitle(event)}</strong>
              <time dateTime={event.occurred_at}>{formatDateTime(event.occurred_at)}</time>
            </div>
            <p className="audit-event__meta">
              {event.entity_type} <code>{event.entity_id}</code> · actor{' '}
              <code>{event.actor}</code>
            </p>
            {eventDetail(event) && <p className="audit-event__detail">{eventDetail(event)}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
