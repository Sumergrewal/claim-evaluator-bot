import type {
  ApiErrorBody,
  ClaimDetailOut,
  ClaimSubmitIn,
  ClaimSummaryOut,
  CoverageRuleOut,
  MemberOut,
} from '../types/api'

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiErrorBody
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((d) => d.msg).join('; ')
    }
  } catch {
    /* ignore */
  }
  return `HTTP ${response.status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response))
  }

  return (await response.json()) as T
}

export function listMembers(): Promise<MemberOut[]> {
  return request<MemberOut[]>('/api/members')
}

export function listCoverageRules(): Promise<CoverageRuleOut[]> {
  return request<CoverageRuleOut[]>('/api/coverage-rules')
}

export function listClaims(memberId?: string): Promise<ClaimSummaryOut[]> {
  const query = memberId ? `?member_id=${encodeURIComponent(memberId)}` : ''
  return request<ClaimSummaryOut[]>(`/api/claims${query}`)
}

export function getClaim(claimId: string): Promise<ClaimDetailOut> {
  return request<ClaimDetailOut>(`/api/claims/${encodeURIComponent(claimId)}`)
}

export function submitClaim(body: ClaimSubmitIn): Promise<ClaimDetailOut> {
  return request<ClaimDetailOut>('/api/claims', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
