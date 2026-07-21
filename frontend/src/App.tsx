import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ConsoleLayout } from './layouts/ConsoleLayout'
import { AnnotationDiffPage } from './pages/AnnotationDiffPage'
import { AnnotationWorkspacePage } from './pages/AnnotationWorkspacePage'
import { EditorialInboxPage } from './pages/EditorialInboxPage'
import { OverviewPage } from './pages/OverviewPage'
import { RunDetailPage } from './pages/RunDetailPage'
import { RunsPage } from './pages/RunsPage'
import { WatchlistAuditPage } from './pages/WatchlistAuditPage'
import { WatchlistPage } from './pages/WatchlistPage'
import './index.css'

const qc = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/console" replace />} />
          <Route path="/console" element={<ConsoleLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
            <Route path="editorial" element={<EditorialInboxPage />} />
            <Route path="editorial/:annotationRunId" element={<AnnotationWorkspacePage />} />
            <Route path="editorial/:annotationRunId/diff" element={<AnnotationDiffPage />} />
            <Route path="watchlist" element={<WatchlistPage />} />
            <Route path="watchlist/audits/:runId" element={<WatchlistAuditPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
