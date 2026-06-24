import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listClaims, listMembers } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { Money } from '../components/Money'
import { StatusBadge } from '../components/StatusBadge'
import type { ClaimSummaryOut, MemberOut } from '../types/api'
import { formatDate } from '../utils/format'

export function ClaimsListPage() {
  const [members, setMembers] = useState<MemberOut[]>([])
  const [claims, setClaims] = useState<ClaimSummaryOut[]>([])
  const [memberFilter, setMemberFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (filter: string) => {
    setLoading(true)
    setError(null)
    try {
      const [memberRows, claimRows] = await Promise.all([
        listMembers(),
        listClaims(filter || undefined),
      ])
      setMembers(memberRows)
      setClaims(claimRows)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(memberFilter)
  }, [memberFilter, load])

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Claims</h1>
          <p className="page-subtitle">Browse submitted claims and their review status.</p>
        </div>
        <Link to="/submit" className="button button--primary">
          Submit new claim
        </Link>
      </div>

      <div className="toolbar">
        <label className="field field--inline">
          <span>Filter by member</span>
          <select
            value={memberFilter}
            onChange={(e) => setMemberFilter(e.target.value)}
            disabled={loading}
          >
            <option value="">All members</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.id})
              </option>
            ))}
          </select>
        </label>
        {!loading && (
          <span className="toolbar__count">
            {claims.length} claim{claims.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {loading && <LoadingState message="Loading claims…" />}
      {!loading && error && <ErrorState message={error} />}
      {!loading && !error && claims.length === 0 && (
        <div className="state-panel">
          <p>No claims found{memberFilter ? ' for this member' : ''}.</p>
          <Link to="/submit" className="button">
            Submit the first claim
          </Link>
        </div>
      )}

      {!loading && !error && claims.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Claim</th>
                <th scope="col">Member</th>
                <th scope="col">Provider</th>
                <th scope="col">Service date</th>
                <th scope="col">Status</th>
                <th scope="col">Charged</th>
                <th scope="col">Plan pays</th>
                <th scope="col">Member pays</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => (
                <tr key={claim.id}>
                  <td>
                    <Link to={`/claims/${claim.id}`} className="claim-link">
                      <code>{claim.id}</code>
                    </Link>
                  </td>
                  <td>{claim.member_name}</td>
                  <td>{claim.provider_name}</td>
                  <td>{formatDate(claim.service_date)}</td>
                  <td>
                    <StatusBadge kind="claim" value={claim.adjudication_state} />
                  </td>
                  <td>
                    <Money value={claim.totals.charged} />
                  </td>
                  <td>
                    <Money value={claim.totals.payable} />
                  </td>
                  <td>
                    <Money value={claim.totals.member_responsibility} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
