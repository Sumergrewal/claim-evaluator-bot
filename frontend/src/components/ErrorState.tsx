import { API_BASE } from '../api/client'

type ErrorStateProps = {
  title?: string
  message: string
}

export function ErrorState({ title = 'Something went wrong', message }: ErrorStateProps) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <h2>{title}</h2>
      <p>{message}</p>
      <p className="hint">
        Make sure the backend is running:{' '}
        <code>uv run uvicorn main:app --reload</code> on <code>{API_BASE}</code>
      </p>
    </div>
  )
}
