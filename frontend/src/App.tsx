import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { NotificationWatcher } from '@/components/health/NotificationWatcher'
import { BookingProvider } from '@/components/health/BookingSheet'
import { UiActionRunner } from '@/components/health/UiActionRunner'
import { AppShell } from '@/components/layout/AppShell'
import { Skeleton } from '@/components/ui/primitives'

const HomePage = lazy(() => import('@/pages/HomePage'))
const CallPage = lazy(() => import('@/pages/CallPage'))
const ChatPage = lazy(() => import('@/pages/ChatPage'))
const HistoryPage = lazy(() => import('@/pages/HistoryPage'))
const ActivityPage = lazy(() => import('@/pages/ActivityPage'))
const AppointmentsPage = lazy(() => import('@/pages/AppointmentsPage'))
const FindCarePage = lazy(() => import('@/pages/FindCarePage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const LanguageSettingsPage = lazy(() => import('@/pages/LanguageSettingsPage'))
const SosPage = lazy(() => import('@/pages/SosPage'))
const FamilyPage = lazy(() => import('@/pages/FamilyPage'))

function PageFallback() {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 p-6" aria-busy aria-label="Loading">
      <Skeleton className="h-9 w-1/3" />
      <Skeleton className="h-40" />
      <Skeleton className="h-24" />
    </div>
  )
}

export default function App() {
  return (
    <BookingProvider>
    <AppShell>
      <NotificationWatcher />
      <UiActionRunner />
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/voice/*" element={<Navigate to="/call" replace />} />
          <Route path="/call" element={<CallPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:id" element={<ChatPage />} />
          <Route path="/appointments" element={<AppointmentsPage />} />
          <Route path="/find-care" element={<FindCarePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/sos" element={<SosPage />} />
          <Route path="/family" element={<FamilyPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/language" element={<LanguageSettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
    </BookingProvider>
  )
}
