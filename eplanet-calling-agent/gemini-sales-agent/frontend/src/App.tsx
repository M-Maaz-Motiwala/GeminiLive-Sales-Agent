import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from '@/src/auth/AuthContext';
import { ProtectedRoute } from '@/src/components/ProtectedRoute';
import { AdminLayout } from '@/src/components/admin/AdminLayout';
import Login from '@/src/pages/admin/Login';
import Dashboard from '@/src/pages/admin/Dashboard';
import Agents from '@/src/pages/admin/Agents';
import Sessions from '@/src/pages/admin/Sessions';
import SessionDetail from '@/src/pages/admin/SessionDetail';
import Leads from '@/src/pages/admin/Leads';
import Outbound from '@/src/pages/admin/Outbound';
import Campaigns from '@/src/pages/admin/Campaigns';
import CampaignDetail from '@/src/pages/admin/CampaignDetail';
import Contacts from '@/src/pages/admin/Contacts';
import ContactDetail from '@/src/pages/admin/ContactDetail';
import Documents from '@/src/pages/admin/Documents';
import Outputs from '@/src/pages/admin/Outputs';
import Notes from '@/src/pages/admin/Notes';
import FAQ from '@/src/pages/admin/FAQ';
import HelpDocs from '@/src/pages/admin/HelpDocs';
import Settings from '@/src/pages/admin/Settings';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/admin" replace />} />
          <Route path="/admin/login" element={<Login />} />
          <Route
            path="/admin"
            element={<ProtectedRoute><AdminLayout /></ProtectedRoute>}
          >
            <Route index element={<Dashboard />} />
            <Route path="agents" element={<Agents />} />
            <Route path="sessions" element={<Sessions />} />
            <Route path="sessions/:id" element={<SessionDetail />} />
            <Route path="leads" element={<Leads />} />
            <Route path="outbound" element={<Outbound />} />
            <Route path="campaigns" element={<Campaigns />} />
            <Route path="campaigns/:id" element={<CampaignDetail />} />
            <Route path="contacts" element={<Contacts />} />
            <Route path="contacts/:id" element={<ContactDetail />} />
            <Route path="documents" element={<Documents />} />
            <Route path="outputs" element={<Outputs />} />
            <Route path="notes" element={<Notes />} />
            <Route path="faq" element={<FAQ />} />
            <Route path="docs" element={<HelpDocs />} />
            <Route path="settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to="/admin/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
