import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AuditEventOut } from '../types/api'
import { AuditTimeline } from './AuditTimeline'

const submittedEvent: AuditEventOut = {
  id: 'A-1',
  event_type: 'claim.submitted',
  entity_type: 'claim',
  entity_id: 'C-001',
  actor: 'member',
  occurred_at: '2026-05-16T09:00:00',
  payload: {
    provider_name: 'Sunrise Dental',
    service_date: '2026-05-15',
    line_item_count: 1,
  },
}

const decidedEvent: AuditEventOut = {
  id: 'A-2',
  event_type: 'line_item.decided',
  entity_type: 'line_item',
  entity_id: 'L-001',
  actor: 'system',
  occurred_at: '2026-05-16T09:00:01',
  payload: {
    outcome: 'approved',
    previous_status: 'pending',
    new_status: 'approved',
    payable_amount: '80.00',
    member_responsibility: '0.00',
  },
}

describe('AuditTimeline', () => {
  it('shows empty state when there are no events', () => {
    render(<AuditTimeline events={[]} />)

    expect(screen.getByText('No audit events recorded.')).toBeInTheDocument()
  })

  it('renders claim submitted events with payload summary', () => {
    render(<AuditTimeline events={[submittedEvent]} />)

    expect(screen.getByText('Claim submitted')).toBeInTheDocument()
    expect(
      screen.getByText(/Provider: Sunrise Dental · Service date: 2026-05-15 · 1 line item\(s\)/),
    ).toBeInTheDocument()
    expect(screen.getByText('member')).toBeInTheDocument()
  })

  it('renders line item decided events with outcome and amounts', () => {
    render(<AuditTimeline events={[decidedEvent]} />)

    expect(screen.getByText('Line item decided')).toBeInTheDocument()
    expect(
      screen.getByText(/Outcome: approved · pending → approved · Plan pays \$80\.00/),
    ).toBeInTheDocument()
  })
})
