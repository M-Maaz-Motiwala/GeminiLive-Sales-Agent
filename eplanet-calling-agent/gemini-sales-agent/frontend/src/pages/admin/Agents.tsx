import { useEffect, useState, type ReactNode } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Plus, Pencil, Trash2, X, Phone } from 'lucide-react';
import { Link } from 'react-router-dom';
import { API_BASE } from '@/src/lib/api';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost, Badge } from '@/src/components/admin/theme';
import { cn } from '@/lib/utils';

const CRM_TOOLS = ['create_lead', 'search_contacts', 'create_note', 'update_lead_status'];
const RAG_TOOLS = ['search_knowledge_base'];
const SEARCH_TOOLS = ['google_search'];
const VOICES = ['Zephyr', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Aoede'];
const MODELS = ['gemini-3.1-flash-live-preview', 'gemini-2.5-flash-native-audio-preview-12-2025'];
const TYPES = ['sales', 'research', 'code_analysis', 'document_qa', 'lead_qualification', 'summarization', 'router'];

const EMPTY = {
  name: '', type: 'sales', system_prompt_template: '', voice: 'Zephyr',
  model: 'gemini-3.1-flash-live-preview', inbound_extension: '',
  enabled_tools: [] as string[], is_active: true,
};

const selectCls = 'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';
const inputCls = selectCls;

export default function Agents() {
  const { token } = useAuth();
  const [agents, setAgents] = useState<any[]>([]);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState({ ...EMPTY });
  const [open, setOpen] = useState(false);
  const [sipServer, setSipServer] = useState('');
  const [error, setError] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = () => fetch(`${API_BASE}/api/agents`, { headers }).then(r => r.json()).then(setAgents).catch(() => {});
  useEffect(() => {
    load();
    fetch(`${API_BASE}/api/system/info`).then(r => r.json()).then(d => setSipServer(d.sip_server || '')).catch(() => {});
  }, [token]);

  const save = async () => {
    setError('');
    const payload = { ...form, inbound_extension: form.inbound_extension.trim() || null };
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

  return (
    <div className="p-6 lg:p-10">
      <PageHeader
        title="AI Agents"
        subtitle="Each agent has a SIP extension — dial from Zoiper on your LAN"
        action={<BtnPrimary onClick={() => { setEditing(null); setForm({ ...EMPTY }); setError(''); setOpen(true); }}><Plus className="w-4 h-4" /> New agent</BtnPrimary>}
      />

      <div className="grid gap-3">
        {agents.map(a => (
          <GlassCard key={a.id} className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-white">{a.name}</span>
                {a.is_active && <Badge variant="success">Active</Badge>}
                {a.inbound_extension && (
                  <Badge variant="default">Ext {a.inbound_extension}</Badge>
                )}
              </div>
              <p className="text-xs text-zinc-500 mt-1">
                {a.type} · {a.voice} · {a.enabled_tools?.length || 0} tools · {a.document_count || 0} KB docs
              </p>
              {a.inbound_extension && sipServer && (
                <p className="text-xs text-violet-400/80 mt-2 flex items-center gap-1">
                  <Phone className="w-3 h-3" /> Zoiper → {sipServer} → dial {a.inbound_extension}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <BtnGhost onClick={() => { setEditing(a); setForm({ name: a.name, type: a.type, system_prompt_template: a.system_prompt_template, voice: a.voice, model: a.model, inbound_extension: a.inbound_extension || '', enabled_tools: a.enabled_tools || [], is_active: a.is_active }); setOpen(true); }}>
                <Pencil className="w-4 h-4" /> Edit
              </BtnGhost>
              <BtnGhost className="text-red-400 border-red-500/20 hover:bg-red-500/10" onClick={() => confirm('Delete?') && fetch(`${API_BASE}/api/agents/${a.id}`, { method: 'DELETE', headers }).then(load)}>
                <Trash2 className="w-4 h-4" />
              </BtnGhost>
            </div>
          </GlassCard>
        ))}
        {agents.length === 0 && <p className="text-zinc-600 text-sm">No agents yet. Run bootstrap or create one.</p>}
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
            <Field label="SIP extension">
              <input className={inputCls} value={form.inbound_extension} placeholder="701" onChange={e => setForm(f => ({ ...f, inbound_extension: e.target.value.replace(/\D/g, '').slice(0, 4) }))} />
              {form.inbound_extension && sipServer && <p className="text-xs text-violet-400 mt-1">Dial {form.inbound_extension} @ {sipServer}</p>}
            </Field>
            <Field label="Type"><select className={selectCls} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>{TYPES.map(t => <option key={t} value={t}>{t}</option>)}</select></Field>
            <Field label="Voice"><select className={selectCls} value={form.voice} onChange={e => setForm(f => ({ ...f, voice: e.target.value }))}>{VOICES.map(v => <option key={v} value={v}>{v}</option>)}</select></Field>
            <Field label="Model"><select className={selectCls} value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))}>{MODELS.map(m => <option key={m} value={m}>{m}</option>)}</select></Field>
            <Field label="System prompt">
              <textarea rows={6} className={cn(inputCls, 'resize-y')} value={form.system_prompt_template} onChange={e => setForm(f => ({ ...f, system_prompt_template: e.target.value }))} />
            </Field>
            <Field label="Tools">
              <div className="space-y-2 text-sm text-zinc-400">
                {[...CRM_TOOLS, ...RAG_TOOLS, ...SEARCH_TOOLS].map(t => (
                  <label key={t} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.enabled_tools.includes(t)} onChange={() => toggleTool(t)} className="rounded accent-violet-600" />
                    {t}
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
