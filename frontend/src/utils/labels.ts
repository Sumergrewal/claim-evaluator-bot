import type {
  ClaimAdjudicationState,
  DecisionOutcome,
  LineItemStatus,
  PhaseName,
  StepResult,
} from '../types/api'

export function claimStateLabel(state: ClaimAdjudicationState): string {
  const labels: Record<ClaimAdjudicationState, string> = {
    submitted: 'Submitted',
    under_review: 'Under review',
    approved: 'Approved',
    denied: 'Denied',
    partially_approved: 'Partially approved',
    paid: 'Paid',
  }
  return labels[state]
}

export function lineItemStatusLabel(status: LineItemStatus): string {
  const labels: Record<LineItemStatus, string> = {
    pending: 'Pending',
    approved: 'Approved',
    denied: 'Denied',
    needs_review: 'Needs review',
  }
  return labels[status]
}

export function decisionOutcomeLabel(outcome: DecisionOutcome): string {
  const labels: Record<DecisionOutcome, string> = {
    approved: 'Approved',
    denied: 'Denied',
    needs_review: 'Needs review',
  }
  return labels[outcome]
}

export function phaseLabel(phase: PhaseName): string {
  const labels: Record<PhaseName, string> = {
    eligibility: 'Eligibility',
    coverage: 'Coverage',
    gates: 'Gates',
    deductible: 'Deductible',
    limits: 'Limits',
    cost_sharing: 'Cost sharing',
  }
  return labels[phase]
}

export function stepResultLabel(result: StepResult): string {
  const labels: Record<StepResult, string> = {
    pass: 'Pass',
    fail: 'Fail',
    applied: 'Applied',
    needs_review: 'Needs review',
  }
  return labels[result]
}

export function claimStateClass(state: ClaimAdjudicationState): string {
  return `badge badge--claim-${state.replace(/_/g, '-')}`
}

export function lineItemStatusClass(status: LineItemStatus): string {
  return `badge badge--line-${status.replace(/_/g, '-')}`
}
