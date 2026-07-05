import { useEffect, useState, useRef, DragEvent } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Upload, Trash2, Loader2, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard, BtnPrimary, Badge } from '@/src/components/admin/theme';
import { API_BASE, apiFetchList } from '@/src/lib/api';

function docBadge(status: string): 'success' | 'warn' | 'default' | 'live' {
  if (status === 'indexed') return 'success';
  if (status === 'indexing') return 'live';
  if (status === 'failed') return 'warn';
  return 'default';
}

const selectCls = 'rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

export default function Documents() {
  const { token, user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [docs, setDocs] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [organizations, setOrganizations] = useState<any[]>([]);
  const [uploadTarget, setUploadTarget] = useState('org');
  const [organizationId, setOrganizationId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [filterKey, setFilterKey] = useState('all');
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [summary, setSummary] = useState<any>({ total: 0, indexed: 0, indexing: 0, pending: 0, failed: 0, remaining: 0 });
  const fileRef = useRef<HTMLInputElement>(null);
  const headers = { Authorization: `Bearer ${token}` };

  const scopeLabel = (d: any) => {
    if (d.agent_id) return agents.find(a => a.id === d.agent_id)?.name || `Agent ${d.agent_id}`;
    if (d.organization_name) return `${d.organization_name} org KB`;
    if (d.organization_id) return `Org ${d.organization_id} KB`;
    return 'Legacy global';
  };

  const load = () => {
    apiFetchList('/api/documents', token).then(setDocs);
    fetch(`${API_BASE}/api/documents/summary`, { headers })
      .then(r => r.json())
      .then(setSummary)
      .catch(() => {});
  };

  useEffect(() => {
    if (!token) return;
    load();
    apiFetchList('/api/agents', token).then(setAgents);
    apiFetchList('/api/organizations', token).then(orgs => {
      setOrganizations(orgs);
      if (orgs[0]?.id) setOrganizationId(String(orgs[0].id));
    });
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [token]);

  const filtered = docs.filter(d => {
    if (filterKey === 'all') return true;
    if (filterKey.startsWith('org:')) return String(d.organization_id) === filterKey.slice(4) && !d.agent_id;
    if (filterKey.startsWith('agent:')) return String(d.agent_id) === filterKey.slice(6);
    return true;
  });

  const upload = async (file: File) => {
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    if (uploadTarget === 'agent' && agentId) {
      fd.append('agent_id', agentId);
    } else if (organizationId) {
      fd.append('organization_id', organizationId);
    }
    await fetch(`${API_BASE}/api/documents`, { method: 'POST', headers, body: fd });
    setUploading(false);
    load();
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); setDragging(false);
    if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
  };

  const del = async (id: number) => {
    if (!confirm('Delete this document and its vectors?')) return;
    await fetch(`${API_BASE}/api/documents/${id}`, { method: 'DELETE', headers });
    load();
  };

  const retryOne = async (id: number) => {
    await fetch(`${API_BASE}/api/documents/${id}/retry`, { method: 'POST', headers });
    load();
  };

  const retryRemaining = async () => {
    await fetch(`${API_BASE}/api/documents/retry-remaining`, { method: 'POST', headers });
    load();
  };

  return (
    <div className="p-6 lg:p-8">
      <PageHeader title="Knowledge Base" subtitle="Per-organization shared KB + optional per-agent overlays" />

      <GlassCard className="p-4 mb-6">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Upload to</label>
            <select value={uploadTarget} onChange={e => setUploadTarget(e.target.value)} className={selectCls}>
              <option value="org">Organization KB (shared)</option>
              <option value="agent">Agent overlay</option>
            </select>
          </div>
          {uploadTarget === 'org' ? (
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Organization</label>
              {isAdmin ? (
                <select value={organizationId} onChange={e => setOrganizationId(e.target.value)} className={selectCls}>
                  {organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              ) : (
                <p className="text-sm text-white py-2 px-1">
                  {organizations.find(o => String(o.id) === String(organizationId))?.name || '—'}
                </p>
              )}
            </div>
          ) : (
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Agent</label>
              <select value={agentId} onChange={e => setAgentId(e.target.value)} className={selectCls}>
                {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Filter</label>
            <select value={filterKey} onChange={e => setFilterKey(e.target.value)} className={selectCls}>
              <option value="all">All</option>
              {organizations.map(o => <option key={o.id} value={`org:${o.id}`}>{o.name} org KB</option>)}
              {agents.map(a => <option key={a.id} value={`agent:${a.id}`}>{a.name}</option>)}
            </select>
          </div>
          <BtnPrimary onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            Upload file
          </BtnPrimary>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
        </div>
      </GlassCard>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={cn(
          'border-2 border-dashed rounded-2xl p-8 text-center mb-6 transition-colors',
          dragging ? 'border-violet-500 bg-violet-500/10' : 'border-white/10 text-zinc-500',
        )}
      >
        Drop PDF, DOCX, or TXT here
      </div>

      <div className="flex flex-wrap gap-2 mb-4 text-xs text-zinc-500">
        <span>{summary.indexed}/{summary.total} indexed</span>
        {summary.remaining > 0 && (
          <button onClick={retryRemaining} className="text-violet-400 hover:underline">Retry remaining ({summary.remaining})</button>
        )}
      </div>

      <div className="space-y-2">
        {filtered.map(d => (
          <GlassCard key={d.id} className="p-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <FileText className="w-5 h-5 text-zinc-500 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm text-white truncate">{d.name}</p>
                <p className="text-xs text-zinc-500">{scopeLabel(d)} · {d.chunk_count || 0} chunks</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Badge variant={docBadge(d.status)}>{d.status}</Badge>
              {d.status === 'failed' && (
                <button onClick={() => retryOne(d.id)} className="text-xs text-violet-400 hover:underline">Retry</button>
              )}
              <button onClick={() => del(d.id)} className="text-red-400 hover:text-red-300"><Trash2 className="w-4 h-4" /></button>
            </div>
          </GlassCard>
        ))}
      </div>
    </div>
  );
}
