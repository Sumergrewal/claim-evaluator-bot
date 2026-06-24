import type { CoverageRuleOut } from '../types/api'

/** Distinct service types covered by the member's policy (sorted). */
export function serviceTypesForMember(
  rules: CoverageRuleOut[],
  memberId: string,
): string[] {
  const types = new Set<string>()
  for (const rule of rules) {
    if (rule.member_id === memberId) {
      types.add(rule.service_type)
    }
  }
  return [...types].sort()
}
