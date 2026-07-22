import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/layout/ProtectedRoute'
import { LoginPage } from './features/auth/LoginPage'
import { RegisterPage } from './features/auth/RegisterPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { GroupsPage } from './features/groups/GroupsPage'
import { GroupDetailPage } from './features/groups/GroupDetailPage'
import { WordFormPage } from './features/words/WordFormPage'
import { RoomsPage } from './features/rooms/RoomsPage'
import { RoomDetailPage } from './features/rooms/RoomDetailPage'
import { ReviewSessionPage } from './features/review/ReviewSessionPage'
import { MnemoLabPage } from './features/mnemolab/MnemoLabPage'
import { MindMapPage } from './features/mindmap/MindMapPage'
import { ProfilePage } from './features/profile/ProfilePage'
import { SettingsPage } from './features/settings/SettingsPage'
import { AdminPage } from './features/admin/AdminPage'
import { LandingPage } from './features/marketing/LandingPage'
import { OnboardingPage } from './features/marketing/OnboardingPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />

      <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />

      <Route path="/groups" element={<ProtectedRoute><GroupsPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId" element={<ProtectedRoute><GroupDetailPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/words/new" element={<ProtectedRoute><WordFormPage /></ProtectedRoute>} />
      <Route path="/groups/:groupId/words/:wordId" element={<ProtectedRoute><WordFormPage /></ProtectedRoute>} />

      <Route path="/rooms" element={<ProtectedRoute><RoomsPage /></ProtectedRoute>} />
      <Route path="/rooms/:roomId" element={<ProtectedRoute><RoomDetailPage /></ProtectedRoute>} />

      <Route path="/review" element={<ProtectedRoute><ReviewSessionPage /></ProtectedRoute>} />

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
