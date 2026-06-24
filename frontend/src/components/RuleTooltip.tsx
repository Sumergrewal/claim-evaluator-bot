import { useRule } from '../context/RulesContext'
import { formatServiceType } from '../utils/format'

type RuleTooltipProps = {
  ruleId: string
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, ' ')
}

export function RuleTooltip({ ruleId }: RuleTooltipProps) {
  const rule = useRule(ruleId)

  if (!rule) {
    return (
      <span className="rule-ref">
        Rule: <code>{ruleId}</code>
      </span>
    )
  }

  return (
    <span className="rule-ref rule-ref--has-tooltip">
      Rule:{' '}
      <span className="rule-tooltip-anchor" tabIndex={0}>
        <code>{ruleId}</code>
        <span className="rule-tooltip" role="tooltip">
          <strong>{rule.policy_name}</strong>
          <span className="rule-tooltip__kind">
            {kindLabel(rule.kind)} · {formatServiceType(rule.service_type)}
          </span>
          <span className="rule-tooltip__body">{rule.description}</span>
          {rule.parameters_summary !== 'No parameters' && (
            <span className="rule-tooltip__meta">{rule.parameters_summary}</span>
          )}
        </span>
      </span>
    </span>
  )
}
