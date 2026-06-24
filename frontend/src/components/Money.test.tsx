import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Money } from './Money'

describe('Money', () => {
  it('renders formatted currency', () => {
    render(<Money value="65.00" />)

    expect(screen.getByText('$65.00')).toHaveClass('money')
  })

  it('uses custom className when provided', () => {
    render(<Money value="10" className="total-cell" />)

    expect(screen.getByText('$10.00')).toHaveClass('total-cell')
  })

  it('renders em dash for null amounts', () => {
    render(<Money value={null} />)

    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
