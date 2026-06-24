import type { ReactNode } from 'react'
import { API_BASE } from '../api/client'

type ErrorStateProps = {
  title?: string
  message: string
  /** Hide the dev-server hint when the API responded (e.g. 404 not found). */
  showBackendHint?: boolean
  footer?: ReactNode
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  showBackendHint = true,
  footer,
}: ErrorStateProps) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <h2>{title}</h2>
      <p>{message}</p>
      {showBackendHint && (
        <p className="hint">
          Make sure the backend is running from the repo root:{' '}
          <code>uv run uvicorn app.main:app --reload</code> (API at{' '}
          <code>{API_BASE}</code>)
        </p>
      )}
      {footer}
    </div>
  )
}
