import { describe, expect, it } from 'vitest'
import { formatDate, formatDateTime, formatMoney, formatServiceType } from './format'

describe('formatMoney', () => {
  it('formats numeric and string amounts as USD', () => {
    expect(formatMoney('120.00')).toBe('$120.00')
    expect(formatMoney(80)).toBe('$80.00')
  })

  it('returns em dash for empty values', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney('')).toBe('—')
  })

  it('returns raw string when value is not numeric', () => {
    expect(formatMoney('not-a-number')).toBe('not-a-number')
  })
})

describe('formatDate', () => {
  it('formats ISO date strings for display', () => {
    expect(formatDate('2026-05-15')).toBe('May 15, 2026')
  })

  it('returns input unchanged when not yyyy-mm-dd', () => {
    expect(formatDate('May 15')).toBe('May 15')
  })
})

describe('formatDateTime', () => {
  it('formats naive ISO timestamps as UTC', () => {
    expect(formatDateTime('2026-05-20T14:30:00')).toMatch(/May 20, 2026/)
  })

  it('returns input when timestamp is invalid', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })
})

describe('formatServiceType', () => {
  it('replaces underscores with spaces', () => {
    expect(formatServiceType('general_consultation')).toBe('general consultation')
    expect(formatServiceType('bariatric_surgery')).toBe('bariatric surgery')
  })
})
