import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getClaim, listClaims, listMembers, submitClaim } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('listMembers fetches /api/members', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([{ id: 'M-001', name: 'Alice Anderson' }]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const members = await listMembers()

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/members',
      expect.objectContaining({ headers: expect.objectContaining({ Accept: 'application/json' }) }),
    )
    expect(members).toEqual([{ id: 'M-001', name: 'Alice Anderson' }])
  })

  it('listClaims encodes member_id filter in query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    await listClaims('M-002')

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/claims?member_id=M-002',
      expect.any(Object),
    )
  })

  it('getClaim throws ApiError with FastAPI detail string on 404', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Claim 'C-404' not found" }, 404)),
    )

    await expect(getClaim('C-404')).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError)
      const apiErr = err as ApiError
      expect(apiErr.status).toBe(404)
      expect(apiErr.message).toBe("Claim 'C-404' not found")
      return true
    })
  })

  it('getClaim falls back to HTTP status when error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('bad gateway', { status: 502 })),
    )

    await expect(getClaim('C-1')).rejects.toMatchObject({
      status: 502,
      message: 'HTTP 502',
    })
  })

  it('submitClaim POSTs JSON body to /api/claims', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: 'C-new', line_items: [], audit_events: [] }, 201),
    )
    vi.stubGlobal('fetch', fetchMock)

    const body = {
      member_id: 'M-001',
      provider_name: 'Clinic',
      service_date: '2026-06-01',
      line_items: [
        {
          service_type: 'mri',
          service_description: 'Knee MRI',
          charged_amount: '500.00',
        },
      ],
    }

    await submitClaim(body)

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/claims',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(body),
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      }),
    )
  })

  it('submitClaim surfaces validation errors from detail array', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: [{ msg: 'field required', type: 'missing' }],
          },
          422,
        ),
      ),
    )

    await expect(
      submitClaim({
        member_id: 'M-001',
        provider_name: 'Clinic',
        service_date: '2026-06-01',
        line_items: [],
      }),
    ).rejects.toMatchObject({
      status: 422,
      message: 'field required',
    })
  })
})
