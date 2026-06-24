/** Wire types mirroring `app/api/schemas.py`. */

export type ClaimAdjudicationState =
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'denied'
  | 'partially_approved'
  | 'paid'

export type LineItemStatus = 'pending' | 'approved' | 'denied' | 'needs_review'

export type DecisionOutcome = 'approved' | 'denied' | 'needs_review'

export type PhaseName =
  | 'eligibility'
  | 'coverage'
  | 'gates'
  | 'deductible'
  | 'limits'
  | 'cost_sharing'

export type StepResult = 'pass' | 'fail' | 'applied' | 'needs_review'

export type MemberOut = {
  id: string
  name: string
}

export type CoverageRuleOut = {
  id: string
  policy_id: string
  policy_name: string
  service_type: string
  kind: string
  parameters: Record<string, unknown>
  description: string
  parameters_summary: string
}

export type ExplanationStepOut = {
  phase: PhaseName
  rule_id: string | null
  result: StepResult
  note: string
  amount?: string | null
  terminating?: boolean | null
}

export type ExplanationOut = {
  outcome: DecisionOutcome
  charged_amount: string
  payable_amount: string
  member_responsibility: string
  steps: ExplanationStepOut[]
  narrative: string
}

export type DecisionOut = {
  id: string
  line_item_id: string
  decided_at: string
  decided_by: string
  outcome: DecisionOutcome
  payable_amount: string
  member_responsibility: string
  deductible_applied: string
  supersedes_id: string | null
  explanation: ExplanationOut
}

export type LineItemOut = {
  id: string
  claim_id: string
  service_type: string
  service_description: string
  charged_amount: string
  preauth_ref: string | null
  status: LineItemStatus
  payable_amount: string | null
  member_responsibility: string | null
  current_decision: DecisionOut | null
}

export type ClaimTotalsOut = {
  charged: string
  payable: string
  member_responsibility: string
}

export type ClaimSummaryOut = {
  id: string
  member_id: string
  member_name: string
  provider_name: string
  service_date: string
  submitted_at: string
  paid_at: string | null
  adjudication_state: ClaimAdjudicationState
  totals: ClaimTotalsOut
}

export type AuditEventOut = {
  id: string
  event_type: string
  entity_type: string
  entity_id: string
  actor: string
  occurred_at: string
  payload: Record<string, unknown>
}

export type ClaimDetailOut = ClaimSummaryOut & {
  line_items: LineItemOut[]
  audit_events: AuditEventOut[]
}

export type LineItemSubmitIn = {
  service_type: string
  service_description: string
  charged_amount: string
  preauth_ref?: string | null
}

export type ClaimSubmitIn = {
  member_id: string
  provider_name: string
  service_date: string
  line_items: LineItemSubmitIn[]
}

export type ApiErrorBody = {
  detail?: string | { msg: string; type?: string; loc?: string[] }[]
}
