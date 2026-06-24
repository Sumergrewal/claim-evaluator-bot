import { useState } from 'react'
import type { LineItemOut } from '../types/api'
import { formatServiceType } from '../utils/format'
import { ExplanationPanel } from './ExplanationPanel'
import { Money } from './Money'
import { StatusBadge } from './StatusBadge'

type LineItemTableProps = {
  lineItems: LineItemOut[]
  onRaiseDispute?: (lineItem: LineItemOut) => void
  disputingLineItemId?: string | null
}

function canDispute(status: LineItemOut['status']): boolean {
  return status === 'approved' || status === 'denied'
}

export function LineItemTable({
  lineItems,
  onRaiseDispute,
  disputingLineItemId = null,
}: LineItemTableProps) {
  const [selectedId, setSelectedId] = useState<string | null>(
    lineItems[0]?.id ?? null,
  )

  const selected = lineItems.find((li) => li.id === selectedId) ?? null

  return (
    <div className="line-items-layout">
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Service</th>
              <th scope="col">Description</th>
              <th scope="col">Charged</th>
              <th scope="col">Status</th>
              <th scope="col">Plan pays</th>
              <th scope="col">Member pays</th>
            </tr>
          </thead>
          <tbody>
            {lineItems.map((li) => {
              const isSelected = li.id === selectedId
              return (
                <tr
                  key={li.id}
                  className={isSelected ? 'data-table__row--selected' : 'data-table__row--clickable'}
                  onClick={() => setSelectedId(li.id)}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedId(li.id)
                    }
                  }}
                  aria-selected={isSelected}
                >
                  <td>
                    <code>{formatServiceType(li.service_type)}</code>
                  </td>
                  <td>{li.service_description}</td>
                  <td>
                    <Money value={li.charged_amount} />
                  </td>
                  <td>
                    <StatusBadge kind="line" value={li.status} />
                  </td>
                  <td>
                    <Money value={li.payable_amount} />
                  </td>
                  <td>
                    <Money value={li.member_responsibility} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <aside className="line-item-detail">
        {selected ? (
          <>
            <h3>{selected.service_description}</h3>
            <dl className="detail-grid detail-grid--compact">
              <div>
                <dt>Line item id</dt>
                <dd>
                  <code>{selected.id}</code>
                </dd>
              </div>
              <div>
                <dt>Service type</dt>
                <dd>
                  <code>{selected.service_type}</code>
                </dd>
              </div>
              {selected.preauth_ref && (
                <div>
                  <dt>Preauth ref</dt>
                  <dd>
                    <code>{selected.preauth_ref}</code>
                  </dd>
                </div>
              )}
            </dl>
            {selected.current_decision ? (
              <ExplanationPanel decision={selected.current_decision} />
            ) : (
              <p className="empty-note">No decision yet — still being reviewed.</p>
            )}
            {onRaiseDispute && canDispute(selected.status) && (
              <div className="line-item-detail__actions">
                <button
                  type="button"
                  className="button"
                  disabled={disputingLineItemId === selected.id}
                  onClick={() => onRaiseDispute(selected)}
                >
                  {disputingLineItemId === selected.id ? 'Submitting…' : 'Raise dispute'}
                </button>
              </div>
            )}
            {selected.status === 'needs_review' && (
              <p className="hint">
                This line is with our team for review. Human evaluation is pending.
              </p>
            )}
          </>
        ) : (
          <p className="empty-note">Select a line item to view its decision.</p>
        )}
      </aside>
    </div>
  )
}
