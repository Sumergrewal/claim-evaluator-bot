import { useEffect, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

type HelloResponse = {
  message: string
  phase: string
}

type FetchState =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HelloResponse }
  | { kind: 'error'; error: string }

function App() {
  const [state, setState] = useState<FetchState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE}/api/hello`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data = (await response.json()) as HelloResponse
        setState({ kind: 'ok', data })
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        const message = err instanceof Error ? err.message : String(err)
        setState({ kind: 'error', error: message })
      })
    return () => controller.abort()
  }, [])

  return (
    <main className="hello-world">
      <h1>claim-evaluator-bot</h1>
      <p className="subtitle">Phase 04 scaffolding — frontend ↔ backend handshake</p>

      {state.kind === 'loading' && <p className="status">Calling backend…</p>}

      {state.kind === 'error' && (
        <p className="status error">
          Backend call failed: <code>{state.error}</code>
          <br />
          Is <code>uvicorn app.main:app --reload</code> running on{' '}
          <code>{API_BASE}</code>?
        </p>
      )}

      {state.kind === 'ok' && (
        <div className="status ok">
          <p>{state.data.message}</p>
          <p>
            Phase reported by API: <code>{state.data.phase}</code>
          </p>
        </div>
      )}
    </main>
  )
}

export default App
