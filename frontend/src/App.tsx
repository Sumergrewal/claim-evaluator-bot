import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { RulesProvider } from './context/RulesContext'
import { ClaimDetailPage } from './pages/ClaimDetailPage'
import { ClaimsListPage } from './pages/ClaimsListPage'
import { SubmitClaimPage } from './pages/SubmitClaimPage'
import './App.css'

export default function App() {
  return (
    <RulesProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<ClaimsListPage />} />
            <Route path="claims/:claimId" element={<ClaimDetailPage />} />
            <Route path="submit" element={<SubmitClaimPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </RulesProvider>
  )
}
