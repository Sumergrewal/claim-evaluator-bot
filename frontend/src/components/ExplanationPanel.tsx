import type { DecisionOut } from '../types/api'
import { formatMoney } from '../utils/format'
import {
  decisionOutcomeLabel,
  phaseLabel,
  stepResultLabel,
} from '../utils/labels'
import { RuleTooltip } from './RuleTooltip'
import { StatusBadge } from './StatusBadge'

type ExplanationPanelProps = {
  decision: DecisionOut
}

function decidedByLabel(decidedBy: string): string {
  if (decidedBy === 'system') {
    return 'System (automated — no human reviewer)'
  }
  return decidedBy
}

export function ExplanationPanel({ decision }: ExplanationPanelProps) {
  const { explanation } = decision

  return (
    <div className="explanation-panel">
      <div className="explanation-panel__header">
        <h3>Coverage decision</h3>
        <StatusBadge kind="decision" value={decision.outcome} />
      </div>

      <dl className="detail-grid detail-grid--compact">
        <div>
          <dt>Decided by</dt>
          <dd>{decidedByLabel(decision.decided_by)}</dd>
        </div>
        <div>
          <dt>Plan pays</dt>
          <dd>{formatMoney(decision.payable_amount)}</dd>
        </div>
        <div>
          <dt>Member pays</dt>
          <dd>{formatMoney(decision.member_responsibility)}</dd>
        </div>
        <div>
          <dt>Deductible applied</dt>
          <dd>{formatMoney(decision.deductible_applied)}</dd>
        </div>
      </dl>

      <p className="narrative">{explanation.narrative}</p>

      <h4>Phase-by-phase breakdown</h4>
      <ol className="explanation-steps">
        {explanation.steps.map((step, index) => {
          const isTerminating = step.terminating === true
          const isFail = step.result === 'fail' || step.result === 'needs_review'
          const rowClass = [
            'explanation-step',
            isTerminating ? 'explanation-step--terminating' : '',
            isFail ? 'explanation-step--fail' : '',
          ]
            .filter(Boolean)
            .join(' ')

          return (
            <li key={`${step.phase}-${index}`} className={rowClass}>
              <div className="explanation-step__head">
                <span className="explanation-step__phase">{phaseLabel(step.phase)}</span>
                <span className={`step-result step-result--${step.result}`}>
                  {stepResultLabel(step.result)}
                </span>
              </div>
              <p className="explanation-step__note">{step.note}</p>
              {step.rule_id && (
                <p className="explanation-step__meta">
                  <RuleTooltip ruleId={step.rule_id} />
                </p>
              )}
              {step.amount && (
                <p className="explanation-step__meta">Amount: {formatMoney(step.amount)}</p>
              )}
            </li>
          )
        })}
      </ol>

      <p className="explanation-summary">
        Outcome: <strong>{decisionOutcomeLabel(explanation.outcome)}</strong> — charged{' '}
        {formatMoney(explanation.charged_amount)}, plan pays{' '}
        {formatMoney(explanation.payable_amount)}, member pays{' '}
        {formatMoney(explanation.member_responsibility)}.
      </p>
    </div>
  )
}
