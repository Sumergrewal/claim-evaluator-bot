import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { listCoverageRules } from '../api/client'
import type { CoverageRuleOut } from '../types/api'

type RulesContextValue = {
  rulesById: ReadonlyMap<string, CoverageRuleOut>
  loading: boolean
  error: string | null
}

const RulesContext = createContext<RulesContextValue | null>(null)

export function RulesProvider({ children }: { children: ReactNode }) {
  const [rules, setRules] = useState<CoverageRuleOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listCoverageRules()
      .then(setRules)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => setLoading(false))
  }, [])

  const rulesById = useMemo(
    () => new Map(rules.map((rule) => [rule.id, rule])),
    [rules],
  )

  return (
    <RulesContext.Provider value={{ rulesById, loading, error }}>
      {children}
    </RulesContext.Provider>
  )
}

export function useRules(): RulesContextValue {
  const ctx = useContext(RulesContext)
  if (!ctx) {
    throw new Error('useRules must be used within RulesProvider')
  }
  return ctx
}

export function useRule(ruleId: string | null | undefined): CoverageRuleOut | undefined {
  const { rulesById } = useRules()
  if (!ruleId) return undefined
  return rulesById.get(ruleId)
}
