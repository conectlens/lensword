import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { ProtectedRoute } from './components/layout/ProtectedRoute'
import { GuestOnlyRoute } from './components/layout/GuestOnlyRoute'
import { LoginPage } from './features/auth/LoginPage'
import { RegisterPage } from './features/auth/RegisterPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { GroupsPage } from './features/groups/GroupsPage'
import { GroupDetailPage } from './features/groups/GroupDetailPage'
import { WordFormPage } from './features/words/WordFormPage'
import { RoomsPage } from './features/rooms/RoomsPage'
import { RoomDetailPage } from './features/rooms/RoomDetailPage'
import { ReviewSessionPage } from './features/review/ReviewSessionPage'
import { AcquisitionSessionPage } from './features/review/AcquisitionSessionPage'
import { MnemoLabPage } from './features/mnemolab/MnemoLabPage'
import { LearningPathsPage } from './features/paths/LearningPathsPage'
import { ConversationPage } from './features/tutor/ConversationPage'
import { ScenarioPage } from './features/tutor/ScenarioPage'
import { PracticeLabPage } from './features/tutor/PracticeLabPage'
import { MindMapPage } from './features/mindmap/MindMapPage'
import { ProfilePage } from './features/profile/ProfilePage'
import { SettingsPage } from './features/settings/SettingsPage'
import { AdminPage } from './features/admin/AdminPage'
import { LandingPage } from './features/marketing/LandingPage'
import { OnboardingPage } from './features/marketing/OnboardingPage'
import { ExtractPage } from './features/extract/ExtractPage'
import { ImportPage } from './features/import/ImportPage'
import { PracticePage } from './features/practice/PracticePage'
import { WeeklyReportPage } from './features/reports/WeeklyReportPage'
import { OAuthAuthorizePage } from './features/mcp/OAuthAuthorizePage'
import { useAuth } from './context/AuthContext'
import { useDesktopNotifications } from './lib/useDesktopNotifications'
import { useOfflineSync } from './lib/useOfflineSync'
import { useWebNotifications } from './lib/useWebNotifications'
import { useTraySync } from './lib/useTraySync'

export default function App() {
  // Only while signed in: the outbox endpoint is authenticated, and polling it
  // without a token would produce nothing but 401s. A no-op in the browser
  // build (ROADMAP 3.2).
  const { user } = useAuth()
  const navigate = useNavigate()
  useDesktopNotifications(user !== null)
  // The web counterpart (issue #345). It never asks for permission — it only
  // polls once the user has granted it from Settings, and it stands down
  // inside the desktop shell so a reminder is not shown twice.
  useWebNotifications(user !== null)
  useOfflineSync(user !== null)
  useTraySync({ enabled: user !== null, isAdmin: user?.role === 'admin', navigate })

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<GuestOnlyRoute><LoginPage /></GuestOnlyRoute>} />
      <Route path="/register" element={<GuestOnlyRoute><RegisterPage /></GuestOnlyRoute>} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      {/* Not wrapped in ProtectedRoute: an external OAuth client (Claude.ai)
          opens this URL directly, and ProtectedRoute always wraps its
          children in AppShell's full nav chrome, which a one-off consent
          screen shouldn't have. OAuthAuthorizePage does its own
          user/loading check and its own redirect-to-login (preserving this
          URL via ?next=) instead. */}
      <Route path="/oauth/authorize" element={<OAuthAuthorizePage />} />

      <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/reports/weekly" element={<ProtectedRoute><WeeklyReportPage /></ProtectedRoute>} />
      <Route path="/reports/weekly/:reportId" element={<ProtectedRoute><WeeklyReportPage /></ProtectedRoute>} />

      <Route path="/groups" element={<ProtectedRoute><GroupsPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId" element={<ProtectedRoute><GroupDetailPage /></ProtectedRoute>} />
      {/* No group in the URL: the tray's "Add word" quick action lands here
          (issue #82), and WordFormPage picks a group itself rather than
          needing one named up front. */}
      <Route path="/words/new" element={<ProtectedRoute><WordFormPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/words/new" element={<ProtectedRoute><WordFormPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/words/:wordId" element={<ProtectedRoute><WordFormPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/extract" element={<ProtectedRoute><ExtractPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/import" element={<ProtectedRoute><ImportPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/practice" element={<ProtectedRoute><PracticePage /></ProtectedRoute>} />

      <Route path="/rooms" element={<ProtectedRoute><RoomsPage /></ProtectedRoute>} />
      <Route path="/rooms/:roomId" element={<ProtectedRoute><RoomDetailPage /></ProtectedRoute>} />

      <Route path="/review" element={<ProtectedRoute><ReviewSessionPage /></ProtectedRoute>} />
      <Route path="/stabilize" element={<ProtectedRoute><AcquisitionSessionPage /></ProtectedRoute>} />

      <Route path="/paths" element={<ProtectedRoute><LearningPathsPage /></ProtectedRoute>} />
      <Route path="/tutor" element={<ProtectedRoute><ConversationPage /></ProtectedRoute>} />
      <Route path="/roleplay" element={<ProtectedRoute><ScenarioPage /></ProtectedRoute>} />
      <Route path="/lab" element={<ProtectedRoute><PracticeLabPage /></ProtectedRoute>} />
      <Route path="/mnemolab" element={<ProtectedRoute><MnemoLabPage /></ProtectedRoute>} />
      <Route path="/mnemolab/:wordId" element={<ProtectedRoute><MnemoLabPage /></ProtectedRoute>} />
      <Route path="/mindmap/:wordId" element={<ProtectedRoute><MindMapPage /></ProtectedRoute>} />

      <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
      <Route path="/admin" element={<ProtectedRoute adminOnly><AdminPage /></ProtectedRoute>} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
