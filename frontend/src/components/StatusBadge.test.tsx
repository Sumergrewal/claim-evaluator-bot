import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('renders claim state label and CSS class', () => {
    render(<StatusBadge kind="claim" value="partially_approved" />)

    const badge = screen.getByText('Partially approved')
    expect(badge).toHaveClass('badge', 'badge--claim-partially-approved')
  })

  it('renders line item status label and CSS class', () => {
    render(<StatusBadge kind="line" value="needs_review" />)

    const badge = screen.getByText('Needs review')
    expect(badge).toHaveClass('badge', 'badge--line-needs-review')
  })

  it('renders decision outcome label', () => {
    render(<StatusBadge kind="decision" value="denied" />)

    expect(screen.getByText('Denied')).toHaveClass('badge', 'badge--decision-denied')
  })
})
