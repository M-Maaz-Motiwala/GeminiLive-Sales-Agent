import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard, Bot, PhoneCall, PhoneOutgoing, Users, UserCheck,
  FileText, Layers, LogOut, StickyNote, Headphones,
  HelpCircle, BookOpen,
} from 'lucide-react';

const NAV = [
  { to: '/admin', icon: LayoutDashboard, label: 'Command Center', end: true },
  { to: '/admin/agents', icon: Bot, label: 'AI Agents' },
  { to: '/admin/sessions', icon: PhoneCall, label: 'Call Sessions' },
  { to: '/admin/outbound', icon: PhoneOutgoing, label: 'Outbound Calls' },
  { to: '/admin/leads', icon: UserCheck, label: 'Leads' },
  { to: '/admin/contacts', icon: Users, label: 'Contacts' },
  { to: '/admin/documents', icon: FileText, label: 'Knowledge Base' },
  { to: '/admin/outputs', icon: Layers, label: 'Outputs' },
  { to: '/admin/notes', icon: StickyNote, label: 'Notes' },
];

const NAV_HELP = [
  { to: '/admin/docs', icon: BookOpen, label: 'Help & Docs' },
  { to: '/admin/faq', icon: HelpCircle, label: 'FAQ' },
];

export function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate('/admin/login'); };

  return (
    <div className="flex h-screen bg-[#07070b] text-zinc-100 overflow-hidden">
      {/* Ambient gradient */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-violet-600/10 rounded-full blur-[120px]" />
        <div className="absolute bottom-0 right-1/4 w-[500px] h-[500px] bg-cyan-600/8 rounded-full blur-[100px]" />
      </div>

      <aside className="relative z-10 w-64 flex flex-col shrink-0 border-r border-white/[0.06] bg-black/40 backdrop-blur-2xl">
        <div className="p-6 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-600 shadow-lg shadow-violet-900/50">
              <Headphones className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white">Aura CC</h1>
              <p className="text-[10px] font-medium uppercase tracking-[0.15em] text-zinc-500">AI Call Platform</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all',
                  isActive
                    ? 'bg-gradient-to-r from-violet-600/25 to-fuchsia-600/10 text-white border border-violet-500/30 shadow-inner'
                    : 'text-zinc-500 hover:text-zinc-200 hover:bg-white/[0.04]',
                )
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </NavLink>
          ))}

          <div className="pt-3 mt-3 border-t border-white/[0.06]">
            <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Help</p>
            {NAV_HELP.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all',
                    isActive
                      ? 'bg-gradient-to-r from-violet-600/25 to-fuchsia-600/10 text-white border border-violet-500/30 shadow-inner'
                      : 'text-zinc-500 hover:text-zinc-200 hover:bg-white/[0.04]',
                  )
                }
              >
                <Icon className="w-4 h-4 shrink-0" />
                {label}
              </NavLink>
            ))}
          </div>
        </nav>

        <div className="p-4 border-t border-white/[0.06]">
          <div className="px-3 py-2 mb-2">
            <p className="text-xs font-medium text-zinc-300 truncate">{user?.full_name || 'Admin'}</p>
            <p className="text-[10px] text-zinc-600 truncate">{user?.email}</p>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 w-full px-3 py-2.5 rounded-xl text-sm font-medium text-red-400/90 hover:bg-red-500/10 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      <main className="relative z-10 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
