import { describe, expect, it } from 'vitest'
import type { CoverageRuleOut } from '../types/api'
import { serviceTypesForMember } from './serviceTypes'

const RULES: CoverageRuleOut[] = [
  {
    id: 'R-1',
    policy_id: 'P-BASIC',
    policy_name: 'Basic',
    member_id: 'M-001',
    service_type: 'physiotherapy',
    kind: 'service_covered',
    parameters: {},
    description: '',
    parameters_summary: '',
  },
  {
    id: 'R-2',
    policy_id: 'P-BASIC',
    policy_name: 'Basic',
    member_id: 'M-001',
    service_type: 'mri',
    kind: 'service_covered',
    parameters: {},
    description: '',
    parameters_summary: '',
  },
  {
    id: 'R-3',
    policy_id: 'P-BASIC',
    policy_name: 'Basic',
    member_id: 'M-001',
    service_type: 'physiotherapy',
    kind: 'copay',
    parameters: {},
    description: '',
    parameters_summary: '',
  },
  {
    id: 'R-4',
    policy_id: 'P-DENTAL',
    policy_name: 'Dental',
    member_id: 'M-003',
    service_type: 'cleaning',
    kind: 'service_covered',
    parameters: {},
    description: '',
    parameters_summary: '',
  },
]

describe('serviceTypesForMember', () => {
  it('returns distinct sorted service types for the member policy', () => {
    expect(serviceTypesForMember(RULES, 'M-001')).toEqual(['mri', 'physiotherapy'])
  })

  it('returns empty list when member has no rules', () => {
    expect(serviceTypesForMember(RULES, 'M-002')).toEqual([])
  })
})
