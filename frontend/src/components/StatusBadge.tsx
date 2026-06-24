import type { ClaimAdjudicationState, DecisionOutcome, LineItemStatus } from '../types/api'
import {
  claimStateClass,
  claimStateLabel,
  decisionOutcomeLabel,
  lineItemStatusClass,
  lineItemStatusLabel,
} from '../utils/labels'

type StatusBadgeProps =
  | { kind: 'claim'; value: ClaimAdjudicationState }
  | { kind: 'line'; value: LineItemStatus }
  | { kind: 'decision'; value: DecisionOutcome }

export function StatusBadge(props: StatusBadgeProps) {
  if (props.kind === 'claim') {
    return (
      <span className={claimStateClass(props.value)}>{claimStateLabel(props.value)}</span>
    )
  }
  if (props.kind === 'line') {
    return (
      <span className={lineItemStatusClass(props.value)}>
        {lineItemStatusLabel(props.value)}
      </span>
    )
  }
  return (
    <span className={`badge badge--decision-${props.value.replace(/_/g, '-')}`}>
      {decisionOutcomeLabel(props.value)}
    </span>
  )
}
