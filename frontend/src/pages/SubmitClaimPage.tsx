import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, listCoverageRules, listMembers, submitClaim } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import type { CoverageRuleOut, LineItemSubmitIn, MemberOut } from '../types/api'
import { formatServiceType } from '../utils/format'
import { serviceTypesForMember } from '../utils/serviceTypes'

type LineItemDraft = LineItemSubmitIn & { key: string }

const EMPTY_LINE: Omit<LineItemDraft, 'key'> = {
  service_type: '',
  service_description: '',
  charged_amount: '',
  preauth_ref: '',
}

function newLineItem(): LineItemDraft {
  return { ...EMPTY_LINE, key: crypto.randomUUID() }
}

export function SubmitClaimPage() {
  const navigate = useNavigate()
  const [members, setMembers] = useState<MemberOut[]>([])
  const [coverageRules, setCoverageRules] = useState<CoverageRuleOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [memberId, setMemberId] = useState('')
  const [providerName, setProviderName] = useState('')
  const [serviceDate, setServiceDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [lineItems, setLineItems] = useState<LineItemDraft[]>(() => [newLineItem()])

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const availableServiceTypes = useMemo(
    () => serviceTypesForMember(coverageRules, memberId),
    [coverageRules, memberId],
  )

  useEffect(() => {
    Promise.all([listMembers(), listCoverageRules()])
      .then(([memberRows, ruleRows]) => {
        setMembers(memberRows)
        setCoverageRules(ruleRows)
        if (memberRows[0]) setMemberId(memberRows[0].id)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (availableServiceTypes.length === 0) return
    setLineItems((rows) =>
      rows.map((row) =>
        row.service_type && !availableServiceTypes.includes(row.service_type)
          ? { ...row, service_type: '' }
          : row,
      ),
    )
  }, [availableServiceTypes])

  function updateLine(key: string, patch: Partial<LineItemDraft>) {
    setLineItems((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  function removeLine(key: string) {
    setLineItems((rows) => (rows.length <= 1 ? rows : rows.filter((row) => row.key !== key)))
  }

  function addLine() {
    setLineItems((rows) => [...rows, newLineItem()])
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitError(null)

    if (!memberId.trim()) {
      setSubmitError('Select a member.')
      return
    }
    if (!providerName.trim()) {
      setSubmitError('Enter a provider name.')
      return
    }
    if (!serviceDate) {
      setSubmitError('Enter a service date.')
      return
    }

    const payloadLineItems: LineItemSubmitIn[] = []
    for (const row of lineItems) {
      if (!row.service_type.trim() || !row.service_description.trim() || !row.charged_amount.trim()) {
        setSubmitError('Each line item needs service type, description, and amount.')
        return
      }
      const amount = Number.parseFloat(row.charged_amount)
      if (Number.isNaN(amount) || amount < 0) {
        setSubmitError('Line item amounts must be non-negative numbers.')
        return
      }
      payloadLineItems.push({
        service_type: row.service_type.trim(),
        service_description: row.service_description.trim(),
        charged_amount: amount.toFixed(2),
        preauth_ref: row.preauth_ref?.trim() || null,
      })
    }

    setSubmitting(true)
    try {
      const created = await submitClaim({
        member_id: memberId,
        provider_name: providerName.trim(),
        service_date: serviceDate,
        line_items: payloadLineItems,
      })
      void navigate(`/claims/${created.id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.message)
      } else {
        setSubmitError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setSubmitting(false)
    }
  }

  const selectedMember = members.find((m) => m.id === memberId)

  if (loading) return <LoadingState message="Loading form…" />
  if (loadError) return <ErrorState message={loadError} />

  return (
    <div className="page page--narrow">
      <Link to="/" className="back-link">
        ← Back to claims
      </Link>

      <div className="page-header">
        <div>
          <h1 className="page-title">Submit claim</h1>
          <p className="page-subtitle">
            File a new claim — each line item is reviewed automatically.
          </p>
        </div>
      </div>

      <form className="card form-card" onSubmit={(e) => void handleSubmit(e)}>
        <fieldset className="form-section" disabled={submitting}>
          <legend>Claim details</legend>
          <label className="field">
            <span>Member</span>
            <select value={memberId} onChange={(e) => setMemberId(e.target.value)} required>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.id})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Provider name</span>
            <input
              type="text"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              placeholder="e.g. City Medical Center"
              required
            />
          </label>
          <label className="field">
            <span>Service date</span>
            <input
              type="date"
              value={serviceDate}
              onChange={(e) => setServiceDate(e.target.value)}
              required
            />
          </label>
        </fieldset>

        <fieldset className="form-section" disabled={submitting}>
          <legend>Line items</legend>
          {lineItems.map((row, index) => (
            <div key={row.key} className="line-item-form">
              <div className="line-item-form__head">
                <strong>Line {index + 1}</strong>
                {lineItems.length > 1 && (
                  <button type="button" className="button button--ghost" onClick={() => removeLine(row.key)}>
                    Remove
                  </button>
                )}
              </div>
              <div className="line-item-form__grid">
                <label className="field">
                  <span>Service type</span>
                  <select
                    value={row.service_type}
                    onChange={(e) => updateLine(row.key, { service_type: e.target.value })}
                    required
                  >
                    <option value="">Select a service type…</option>
                    {availableServiceTypes.map((type) => (
                      <option key={type} value={type}>
                        {formatServiceType(type)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Description</span>
                  <input
                    type="text"
                    value={row.service_description}
                    onChange={(e) => updateLine(row.key, { service_description: e.target.value })}
                    placeholder="e.g. 45-min session"
                    required
                  />
                </label>
                <label className="field">
                  <span>Charged amount</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={row.charged_amount}
                    onChange={(e) => updateLine(row.key, { charged_amount: e.target.value })}
                    placeholder="120.00"
                    required
                  />
                </label>
                <label className="field">
                  <span>Preauth ref (optional)</span>
                  <input
                    type="text"
                    value={row.preauth_ref ?? ''}
                    onChange={(e) => updateLine(row.key, { preauth_ref: e.target.value })}
                    placeholder="Required for some services"
                  />
                </label>
              </div>
            </div>
          ))}
          <button type="button" className="button" onClick={addLine}>
            Add line item
          </button>
        </fieldset>

        {submitError && (
          <div className="form-error" role="alert">
            {submitError}
          </div>
        )}

        <div className="form-actions">
          <button type="submit" className="button button--primary" disabled={submitting}>
            {submitting ? 'Submitting…' : 'Submit & review'}
          </button>
        </div>
      </form>

      <aside className="hint-card">
        <h3>Service types by member</h3>
        <p>
          The dropdown lists services covered on{' '}
          {selectedMember ? <strong>{selectedMember.name}</strong> : 'the selected member'}
          &apos;s policy. Health plans (Alice, Bob) include types like{' '}
          <code>general_consultation</code>, <code>physiotherapy</code>, <code>mri</code>, and{' '}
          <code>bariatric_surgery</code>. Carol&apos;s dental plan adds{' '}
          <code>cleaning</code>, <code>filling</code>, <code>crown</code>,{' '}
          <code>root_canal</code>, and <code>cosmetic_whitening</code> (excluded).
        </p>
      </aside>
    </div>
  )
}
