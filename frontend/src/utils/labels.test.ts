import { describe, expect, it } from 'vitest'
import {
  claimStateClass,
  claimStateLabel,
  decisionOutcomeLabel,
  lineItemStatusClass,
  lineItemStatusLabel,
  phaseLabel,
  stepResultLabel,
} from './labels'

describe('claimStateLabel', () => {
  it('maps every claim state to a readable label', () => {
    expect(claimStateLabel('paid')).toBe('Paid')
    expect(claimStateLabel('partially_approved')).toBe('Partially approved')
    expect(claimStateLabel('under_review')).toBe('Under review')
  })
})

describe('lineItemStatusLabel', () => {
  it('maps line item statuses for the UI', () => {
    expect(lineItemStatusLabel('needs_review')).toBe('Needs review')
    expect(lineItemStatusLabel('approved')).toBe('Approved')
  })
})

describe('decisionOutcomeLabel', () => {
  it('maps decision outcomes for the UI', () => {
    expect(decisionOutcomeLabel('denied')).toBe('Denied')
  })
})

describe('phaseLabel', () => {
  it('maps engine phases to readable names', () => {
    expect(phaseLabel('cost_sharing')).toBe('Cost sharing')
    expect(phaseLabel('eligibility')).toBe('Eligibility')
  })
})

describe('stepResultLabel', () => {
  it('maps step results for explanation rows', () => {
    expect(stepResultLabel('needs_review')).toBe('Needs review')
    expect(stepResultLabel('applied')).toBe('Applied')
  })
})

describe('badge class helpers', () => {
  it('builds stable CSS class names from enum values', () => {
    expect(claimStateClass('partially_approved')).toBe('badge badge--claim-partially-approved')
    expect(lineItemStatusClass('needs_review')).toBe('badge badge--line-needs-review')
  })
})
