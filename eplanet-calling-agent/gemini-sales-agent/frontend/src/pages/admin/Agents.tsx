import { useEffect, useState, type ReactNode } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Plus, Pencil, Trash2, X, Phone, PhoneOutgoing } from 'lucide-react';
import { Link } from 'react-router-dom';
import { API_BASE, apiFetch, apiFetchList, apiFetchPublic } from '@/src/lib/api';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost, Badge } from '@/src/components/admin/theme';
import { cn } from '@/lib/utils';

const CRM_TOOLS = ['create_lead', 'search_contacts', 'create_note', 'update_lead_status'];
const RAG_TOOLS = ['search_knowledge_base'];
const SEARCH_TOOLS = ['google_search'];
const VOICES = ['Zephyr', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Aoede'];
const MODELS = ['gemini-3.1-flash-live-preview', 'gemini-2.5-flash-native-audio-preview-12-2025'];
const TYPES = ['sales', 'outbound_sales', 'research', 'code_analysis', 'document_qa', 'lead_qualification', 'summarization', 'router'];

const EMPTY = {
  name: '', type: 'sales', system_prompt_template: '', voice: 'Zephyr',
  model: 'gemini-3.1-flash-live-preview', inbound_extension: '',
  enabled_tools: [] as string[], is_active: true,
  inbound_prompt_template: '',
  outbound_prompt_template: '',
  master_prompt_override: '',
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

  const [loadError, setLoadError] = useState('');

  const load = async () => {
    setLoadError('');
    try {
      setAgents(await apiFetchList('/api/agents', token));
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
        subtitle="Inbound: dial extension from Zoiper · Outbound: dial from Outbound Calls in CRM"
        action={<BtnPrimary onClick={() => { setEditing(null); setForm({ ...EMPTY }); setError(''); setOpen(true); }}><Plus className="w-4 h-4" /> New agent</BtnPrimary>}
      />

      {loadError && (
        <p className="text-sm text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-2 mb-4">
          {loadError}. <Link to="/admin/login" className="underline">Sign in again</Link>
        </p>
      )}

      <div className="grid gap-3">
        {agents.map(a => (
          <GlassCard key={a.id} className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-white">{a.name}</span>
                {a.is_active && <Badge variant="success">Active</Badge>}
                {a.type === 'outbound_sales' && (
                  <Badge variant="warn">Outbound</Badge>
                )}
                {a.inbound_extension && (
                  <Badge variant="default">Ext {a.inbound_extension}</Badge>
                )}
              </div>
              <p className="text-xs text-zinc-500 mt-1">
                {a.type} · {a.voice} · {a.enabled_tools?.length || 0} tools · {a.document_count || 0} KB docs
              </p>
              {a.type === 'outbound_sales' ? (
                <p className="text-xs text-orange-400/80 mt-2 flex items-center gap-1">
                  <PhoneOutgoing className="w-3 h-3" />
                  <Link to={`/admin/outbound?agent_id=${a.id}`} className="hover:underline">
                    Dial from CRM → Outbound Calls
                  </Link>
                </p>
              ) : a.inbound_extension && sipServer ? (
                <p className="text-xs text-violet-400/80 mt-2 flex items-center gap-1">
                  <Phone className="w-3 h-3" /> Zoiper → {sipServer} → dial {a.inbound_extension}
                </p>
              ) : null}
            </div>
            <div className="flex gap-2 flex-wrap">
              {a.type === 'outbound_sales' && (
                <Link to={`/admin/outbound?agent_id=${a.id}`}>
                  <BtnGhost className="text-orange-300 border-orange-500/20 hover:bg-orange-500/10">
                    <PhoneOutgoing className="w-4 h-4" /> Dial
                  </BtnGhost>
                </Link>
              )}
              <BtnGhost onClick={() => { setEditing(a); setForm({ name: a.name, type: a.type, system_prompt_template: a.system_prompt_template, voice: a.voice, model: a.model, inbound_extension: a.inbound_extension || '', enabled_tools: a.enabled_tools || [], is_active: a.is_active, inbound_prompt_template: a.inbound_prompt_template || '', outbound_prompt_template: a.outbound_prompt_template || '', master_prompt_override: a.master_prompt_override || '' }); setOpen(true); }}>
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
            <Field label="Inbound prompt (persona + call flow for inbound calls)">
              <textarea rows={7} className={cn(inputCls, 'resize-y')} placeholder="Describe the agent's inbound persona and 9-stage funnel behavior..." value={form.inbound_prompt_template} onChange={e => setForm(f => ({ ...f, inbound_prompt_template: e.target.value }))} />
            </Field>
            <Field label="Outbound prompt (persona + call flow for outbound/campaign calls)">
              <textarea rows={7} className={cn(inputCls, 'resize-y')} placeholder="Describe the agent's outbound cold-call persona and 9-stage funnel behavior..." value={form.outbound_prompt_template} onChange={e => setForm(f => ({ ...f, outbound_prompt_template: e.target.value }))} />
            </Field>
            <Field label="System prompt (fallback — used if inbound/outbound prompts are empty)">
              <textarea rows={5} className={cn(inputCls, 'resize-y')} value={form.system_prompt_template} onChange={e => setForm(f => ({ ...f, system_prompt_template: e.target.value }))} />
            </Field>
            <Field label="Master prompt override (overrides global rules for this agent only — leave blank to use global)">
              <textarea rows={5} className={cn(inputCls, 'resize-y')} placeholder="Leave blank to use the global master prompt from Settings..." value={form.master_prompt_override} onChange={e => setForm(f => ({ ...f, master_prompt_override: e.target.value }))} />
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
