type LoadingStateProps = {
  message?: string
}

export function LoadingState({ message = 'Loading…' }: LoadingStateProps) {
  return (
    <div className="state-panel" role="status">
      <div className="spinner" aria-hidden="true" />
      <p>{message}</p>
    </div>
  )
}
