import { useEffect, useState, type ReactNode } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Plus, Pencil, Trash2, X, Phone, PhoneOutgoing } from 'lucide-react';
import { Link } from 'react-router-dom';
import { API_BASE, apiFetch, apiFetchList, apiFetchPublic } from '@/src/lib/api';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost, Badge } from '@/src/components/admin/theme';
import { cn } from '@/lib/utils';

const CRM_TOOLS = ['create_lead', 'search_contacts', 'create_note', 'update_lead_status'];
const CALENDAR_TOOLS = ['find_next_available_slot', 'list_available_slots', 'schedule_meeting', 'cancel_meeting'];
const RAG_TOOLS = ['search_knowledge_base'];
const SEARCH_TOOLS = ['google_search'];
const SYSTEM_TOOLS = ['end_call'];
const VOICES = [
  { name: 'Zephyr', style: 'Bright', gender: 'female' },
  { name: 'Puck', style: 'Upbeat', gender: 'male' },
  { name: 'Charon', style: 'Informative', gender: 'male' },
  { name: 'Kore', style: 'Firm', gender: 'female' },
  { name: 'Fenrir', style: 'Excitable', gender: 'male' },
  { name: 'Leda', style: 'Youthful', gender: 'female' },
  { name: 'Orus', style: 'Firm', gender: 'male' },
  { name: 'Aoede', style: 'Breezy', gender: 'female' },
  { name: 'Callirrhoe', style: 'Easy-going', gender: 'female' },
  { name: 'Autonoe', style: 'Bright', gender: 'female' },
  { name: 'Enceladus', style: 'Breathy', gender: 'male' },
  { name: 'Iapetus', style: 'Clear', gender: 'male' },
  { name: 'Algieba', style: 'Smooth', gender: 'male' },
  { name: 'Despina', style: 'Smooth', gender: 'female' },
  { name: 'Erinome', style: 'Clear', gender: 'female' },
  { name: 'Algenib', style: 'Gravelly', gender: 'male' },
  { name: 'Rasalgethi', style: 'Informative', gender: 'male' },
  { name: 'Laomedeia', style: 'Upbeat', gender: 'female' },
  { name: 'Achernar', style: 'Soft', gender: 'female' },
  { name: 'Alnilam', style: 'Firm', gender: 'male' },
  { name: 'Schedar', style: 'Even', gender: 'male' },
  { name: 'Gacrux', style: 'Mature', gender: 'female' },
  { name: 'Pulcherrima', style: 'Forward', gender: 'female' },
  { name: 'Achird', style: 'Friendly', gender: 'male' },
  { name: 'Zubenelgenubi', style: 'Casual', gender: 'male' },
  { name: 'Vindemiatrix', style: 'Gentle', gender: 'female' },
  { name: 'Sadachbia', style: 'Lively', gender: 'male' },
  { name: 'Sadaltager', style: 'Knowledgeable', gender: 'male' },
  { name: 'Sulafat', style: 'Warm', gender: 'female' },
  { name: 'Arcas', style: 'Specialty', gender: 'male' },
];
const MODELS = ['gemini-3.1-flash-live-preview', 'gemini-2.5-flash-native-audio-preview-12-2025'];

const getVoiceOptions = (gender: string) => VOICES.filter(v => v.gender === gender);

const getDefaultVoiceForGender = (gender: string) => getVoiceOptions(gender)[0]?.name || VOICES[0]?.name || 'Zephyr';

const EMPTY = {
  name: '',
  organization_id: '',
  type: 'sales',
  voice: 'Zephyr',
  voice_gender: 'female',
  model: 'gemini-3.1-flash-live-preview',
  enabled_tools: [] as string[],
  is_active: true,
  inbound_prompt_template: '',
  outbound_prompt_template: '',
};

const selectCls = 'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';
const inputCls = selectCls;

export default function Agents() {
  const { token, user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [agents, setAgents] = useState<any[]>([]);
  const [organizations, setOrganizations] = useState<any[]>([]);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState({ ...EMPTY });
  const [open, setOpen] = useState(false);
  const [sipServer, setSipServer] = useState('');
  const [error, setError] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const [loadError, setLoadError] = useState('');
  const voiceOptions = getVoiceOptions(form.voice_gender);

  const load = async () => {
    setLoadError('');
    try {
      setAgents(await apiFetchList('/api/agents', token));
      setOrganizations(await apiFetchList('/api/organizations', token));
    } catch (e) {
      setAgents([]);
      setLoadError(e instanceof Error ? e.message : 'Failed to load agents');
    }
  };

  useEffect(() => {
    if (!token) return;
    load();
    apiFetchPublic<{ sip_server?: string }>('/api/system/info')
      .then(d => setSipServer(d.sip_server || ''))
      .catch(() => {});
  }, [token]);

  const save = async () => {
    setError('');
    if (!form.organization_id) {
      setError('Select an organization');
      return;
    }
    const payload = {
      ...form,
      organization_id: Number(form.organization_id),
    };
    const res = await fetch(
      editing ? `${API_BASE}/api/agents/${editing.id}` : `${API_BASE}/api/agents`,
      { method: editing ? 'PUT' : 'POST', headers, body: JSON.stringify(payload) },
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setError(typeof err.detail === 'string' ? err.detail : err.detail?.[0]?.msg || 'Save failed');
      return;
    }
    setOpen(false);
    load();
  };

  const toggleTool = (tool: string) => {
    setForm(f => ({
      ...f,
      enabled_tools: f.enabled_tools.includes(tool) ? f.enabled_tools.filter(t => t !== tool) : [...f.enabled_tools, tool],
    }));
  };

  const updateVoiceGender = (voiceGender: string) => {
    setForm(f => {
      const nextVoiceOptions = getVoiceOptions(voiceGender);
      const nextVoice = nextVoiceOptions.some(v => v.name === f.voice)
        ? f.voice
        : nextVoiceOptions[0]?.name || f.voice;
      return {
        ...f,
        voice_gender: voiceGender,
        voice: nextVoice,
      };
    });
  };

  return (
    <div className="p-6 lg:p-10">
      <PageHeader
        title="AI Agents"
        subtitle="Sales agents belong to an organization — shared DID for inbound pool and outbound caller ID"
        action={<BtnPrimary onClick={() => { setEditing(null); setForm({ ...EMPTY, organization_id: organizations[0]?.id ? String(organizations[0].id) : '' }); setError(''); setOpen(true); }}><Plus className="w-4 h-4" /> New agent</BtnPrimary>}
      />

      {loadError && (
        <p className="text-sm text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-2 mb-4">
          {loadError}. <Link to="/admin/login" className="underline">Sign in again</Link>
        </p>
      )}

      {organizations.length === 0 && (
        <p className="text-sm text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-2 mb-4">
          No organizations yet. <Link to="/admin/organizations" className="underline">Create an organization</Link> first.
        </p>
      )}

      <div className="grid gap-3">
        {agents.map(a => (
          <GlassCard key={a.id} className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-white">{a.name}</span>
                {a.is_active && <Badge variant="success">Active</Badge>}
                {a.inbound_extension && <Badge variant="default">Ext {a.inbound_extension}</Badge>}
                {a.organization_name && <Badge variant="default">{a.organization_name}</Badge>}
                {a.did && <Badge variant="default">DID {a.did}</Badge>}
              </div>
              <p className="text-xs text-zinc-500 mt-1">
                {a.type} · {a.voice} ({a.voice_gender}) · {a.enabled_tools?.length || 0} tools · {a.document_count || 0} agent KB docs
              </p>
              <p className="text-xs text-orange-400/80 mt-2 flex items-center gap-1">
                <PhoneOutgoing className="w-3 h-3" />
                <Link to={`/admin/outbound?agent_id=${a.id}`} className="hover:underline">Outbound dial from CRM</Link>
              </p>
              {a.inbound_extension && sipServer ? (
                <p className="text-xs text-violet-400/80 mt-1 flex items-center gap-1">
                  <Phone className="w-3 h-3" /> Lab dial {a.inbound_extension} @ {sipServer}
                </p>
              ) : null}
            </div>
            <div className="flex gap-2 flex-wrap">
              <Link to={`/admin/outbound?agent_id=${a.id}`}>
                <BtnGhost className="text-orange-300 border-orange-500/20 hover:bg-orange-500/10">
                  <PhoneOutgoing className="w-4 h-4" /> Dial
                </BtnGhost>
              </Link>
              <BtnGhost onClick={() => {
                setEditing(a);
                setForm({
                  name: a.name,
                  organization_id: a.organization_id ? String(a.organization_id) : '',
                  type: 'sales',
                  voice: a.voice,
                  voice_gender: a.voice_gender || 'female',
                  model: a.model,
                  enabled_tools: a.enabled_tools || [],
                  is_active: a.is_active,
                  inbound_prompt_template: a.inbound_prompt_template || '',
                  outbound_prompt_template: a.outbound_prompt_template || '',
                });
                setOpen(true);
              }}>
                <Pencil className="w-4 h-4" /> Edit
              </BtnGhost>
              <BtnGhost className="text-red-400 border-red-500/20 hover:bg-red-500/10" onClick={() => confirm('Delete?') && fetch(`${API_BASE}/api/agents/${a.id}`, { method: 'DELETE', headers }).then(load)}>
                <Trash2 className="w-4 h-4" />
              </BtnGhost>
            </div>
          </GlassCard>
        ))}
        {agents.length === 0 && <p className="text-zinc-600 text-sm">No agents yet.</p>}
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex">
          <div className="flex-1 bg-black/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="w-full max-w-lg bg-[#0c0c12] border-l border-white/10 h-full overflow-auto p-6 space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-bold text-white">{editing ? 'Edit agent' : 'New agent'}</h3>
              <button onClick={() => setOpen(false)} className="text-zinc-500 hover:text-white"><X className="w-5 h-5" /></button>
            </div>
            {error && <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2">{error}</p>}
            <Field label="Name"><input className={inputCls} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></Field>
            <Field label="Organization">
              {isAdmin ? (
                <select className={selectCls} value={form.organization_id} onChange={e => setForm(f => ({ ...f, organization_id: e.target.value }))}>
                  <option value="">Select organization…</option>
                  {organizations.map(o => (
                    <option key={o.id} value={o.id}>{o.name} — DID {o.did}</option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-white py-2">
                  {organizations.find(o => String(o.id) === String(form.organization_id))?.name || '—'}
                </p>
              )}
              {isAdmin && (
                <p className="text-xs text-zinc-500 mt-1">
                  <Link to="/admin/organizations" className="text-violet-400 hover:underline">Add organization</Link> to register a new DID first.
                </p>
              )}
            </Field>
            <Field label="Voice">
              <select className={selectCls} value={form.voice} onChange={e => setForm(f => ({ ...f, voice: e.target.value }))}>
                {voiceOptions.map(v => (
                  <option key={v.name} value={v.name}>
                    {v.name} - {v.style}{v.name === 'Sulafat' ? ' (most human-like)' : ''}
                  </option>
                ))}
              </select>
              <p className="text-xs text-zinc-500 mt-1">
                Showing {form.voice_gender === 'male' ? 'male' : 'female'} voices only.
              </p>
            </Field>
            <Field label="Voice Gender">
              <select className={selectCls} value={form.voice_gender} onChange={e => updateVoiceGender(e.target.value)}>
                <option value="female">Female</option>
                <option value="male">Male</option>
              </select>
            </Field>
            <Field label="Model"><select className={selectCls} value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))}>{MODELS.map(m => <option key={m} value={m}>{m}</option>)}</select></Field>
            <Field label="Inbound prompt">
              <textarea rows={8} className={cn(inputCls, 'resize-y')} placeholder="Inbound persona for this organization..." value={form.inbound_prompt_template} onChange={e => setForm(f => ({ ...f, inbound_prompt_template: e.target.value }))} />
            </Field>
            <Field label="Outbound prompt">
              <textarea rows={8} className={cn(inputCls, 'resize-y')} placeholder="Outbound cold-call persona..." value={form.outbound_prompt_template} onChange={e => setForm(f => ({ ...f, outbound_prompt_template: e.target.value }))} />
            </Field>
            {editing?.inbound_extension && <p className="text-xs text-zinc-500">SIP extension {editing.inbound_extension} (auto-assigned)</p>}
            {!editing && <p className="text-xs text-zinc-500">SIP lab extension is assigned automatically.</p>}
            <Field label="Tools">
              <div className="space-y-2 text-sm text-zinc-400">
                <p className="text-[10px] uppercase tracking-wider text-zinc-600">CRM</p>
                {CRM_TOOLS.map(t => (
                  <label key={t} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.enabled_tools.includes(t)} onChange={() => toggleTool(t)} className="rounded accent-violet-600" />
                    {t}
                  </label>
                ))}
                <p className="text-[10px] uppercase tracking-wider text-zinc-600 pt-2">Knowledge base</p>
                {RAG_TOOLS.map(t => (
                  <label key={t} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.enabled_tools.includes(t)} onChange={() => toggleTool(t)} className="rounded accent-violet-600" />
                    {t}
                  </label>
                ))}
                <p className="text-[10px] uppercase tracking-wider text-zinc-600 pt-2">Calendar</p>
                {CALENDAR_TOOLS.map(t => (
                  <label key={t} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.enabled_tools.includes(t)} onChange={() => toggleTool(t)} className="rounded accent-violet-600" />
                    {t}
                  </label>
                ))}
                <p className="text-[10px] uppercase tracking-wider text-zinc-600 pt-2">Search</p>
                {SEARCH_TOOLS.map(t => (
                  <label key={t} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.enabled_tools.includes(t)} onChange={() => toggleTool(t)} className="rounded accent-violet-600" />
                    {t}
                  </label>
                ))}
                <p className="text-[10px] uppercase tracking-wider text-zinc-600 pt-2">System</p>
                {SYSTEM_TOOLS.map(t => (
                  <label key={t} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked disabled className="rounded accent-violet-600 opacity-60" />
                    {t} <span className="text-[10px] text-zinc-600">(always on)</span>
                  </label>
                ))}
              </div>
            </Field>
            <label className="flex items-center gap-2 text-sm text-zinc-400">
              <input type="checkbox" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} className="accent-violet-600" />
              Active
            </label>
            <BtnPrimary onClick={save} className="w-full">{editing ? 'Save' : 'Create'}</BtnPrimary>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">{label}</label>
      {children}
    </div>
  );
}
