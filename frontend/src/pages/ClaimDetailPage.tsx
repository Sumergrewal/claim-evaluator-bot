import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getClaim } from '../api/client'
import { AuditTimeline } from '../components/AuditTimeline'
import { ErrorState } from '../components/ErrorState'
import { LineItemTable } from '../components/LineItemTable'
import { LoadingState } from '../components/LoadingState'
import { Money } from '../components/Money'
import { StatusBadge } from '../components/StatusBadge'
import type { ClaimDetailOut } from '../types/api'
import { formatDate, formatDateTime } from '../utils/format'

export function ClaimDetailPage() {
  const { claimId } = useParams<{ claimId: string }>()
  const [claim, setClaim] = useState<ClaimDetailOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!claimId) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)

    getClaim(claimId)
      .then(setClaim)
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [claimId])

  if (!claimId) {
    return <ErrorState title="Missing claim id" message="No claim id in the URL." />
  }

  if (loading) return <LoadingState message="Loading claim…" />
  if (error) return <ErrorState message={error} />
  if (!claim) return <ErrorState message="Claim not found." />

  return (
    <div className="page">
      <Link to="/" className="back-link">
        ← Back to claims
      </Link>

      <div className="page-header">
        <div>
          <h1 className="page-title">
            Claim <code>{claim.id}</code>
          </h1>
          <p className="page-subtitle">
            {claim.member_name} · {claim.provider_name}
          </p>
        </div>
        <StatusBadge kind="claim" value={claim.adjudication_state} />
      </div>

      <section className="card summary-card">
        <h2>Summary</h2>
        <dl className="detail-grid">
          <div>
            <dt>Member</dt>
            <dd>
              {claim.member_name} (<code>{claim.member_id}</code>)
            </dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>{claim.provider_name}</dd>
          </div>
          <div>
            <dt>Service date</dt>
            <dd>{formatDate(claim.service_date)}</dd>
          </div>
          <div>
            <dt>Submitted</dt>
            <dd>{formatDateTime(claim.submitted_at)}</dd>
          </div>
          <div>
            <dt>Paid</dt>
            <dd>{claim.paid_at ? formatDateTime(claim.paid_at) : 'Not paid'}</dd>
          </div>
          <div>
            <dt>Total charged</dt>
            <dd>
              <Money value={claim.totals.charged} />
            </dd>
          </div>
          <div>
            <dt>Plan pays</dt>
            <dd>
              <Money value={claim.totals.payable} />
            </dd>
          </div>
          <div>
            <dt>Member responsibility</dt>
            <dd>
              <Money value={claim.totals.member_responsibility} />
            </dd>
          </div>
        </dl>
      </section>

      <section className="card">
        <h2>Line items &amp; decisions</h2>
        <p className="section-hint">Click a row to see why this line was approved, denied, or flagged.</p>
        <LineItemTable lineItems={claim.line_items} />
      </section>

      <section className="card">
        <h2>Audit timeline</h2>
        <AuditTimeline events={claim.audit_events} />
      </section>
    </div>
  )
}
