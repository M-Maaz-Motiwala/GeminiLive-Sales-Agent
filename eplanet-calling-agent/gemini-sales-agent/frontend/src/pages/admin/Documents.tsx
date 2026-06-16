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
  const { token } = useAuth();
  const [docs, setDocs] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [agentId, setAgentId] = useState('');
  const [filterAgentId, setFilterAgentId] = useState('all');
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [summary, setSummary] = useState<any>({ total: 0, indexed: 0, indexing: 0, pending: 0, failed: 0, remaining: 0 });
  const fileRef = useRef<HTMLInputElement>(null);
  const headers = { Authorization: `Bearer ${token}` };

  const agentName = (id: number) => agents.find(a => a.id === id)?.name || `Agent ${id}`;

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
    apiFetchList('/api/agents', token).then(d => {
      setAgents(d);
      if (d[0]) setAgentId(String(d[0].id));
    });
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [token]);

  const filtered = filterAgentId === 'all' ? docs : docs.filter(d => String(d.agent_id) === filterAgentId);

  const upload = async (file: File) => {
    if (!agentId) return;
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('agent_id', agentId);
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
      <PageHeader title="Knowledge Base" subtitle="Upload RAG documents per agent — PDF, DOCX, TXT" />

      <GlassCard className="p-4 mb-6">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Upload for agent</label>
            <select value={agentId} onChange={e => setAgentId(e.target.value)} className={selectCls}>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}{a.inbound_extension ? ` (ext ${a.inbound_extension})` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Filter</label>
            <select value={filterAgentId} onChange={e => setFilterAgentId(e.target.value)} className={selectCls}>
              <option value="all">All agents</option>
              {agents.map(a => <option key={a.id} value={String(a.id)}>{a.name}</option>)}
            </select>
          </div>
          <BtnPrimary onClick={() => fileRef.current?.click()} disabled={uploading || !agentId}>
            {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            Upload file
          </BtnPrimary>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
        </div>
      </GlassCard>

      <GlassCard className="p-4 mb-6">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <Badge variant="default">Total: {summary.total}</Badge>
          <Badge variant="success">Indexed: {summary.indexed}</Badge>
          <Badge variant="live">Indexing: {summary.indexing}</Badge>
          <Badge variant="default">Pending: {summary.pending}</Badge>
          <Badge variant="warn">Failed: {summary.failed}</Badge>
          <Badge variant="warn">Remaining: {summary.remaining}</Badge>
          <BtnPrimary onClick={retryRemaining} disabled={!summary.remaining}>
            Retry Remaining
          </BtnPrimary>
        </div>
      </GlassCard>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={cn(
          'rounded-2xl border-2 border-dashed p-10 text-center mb-6 transition-all',
          dragging ? 'border-violet-500/60 bg-violet-500/5 text-zinc-300' : 'border-white/10 text-zinc-500',
        )}
      >
        <Upload className="w-6 h-6 mx-auto mb-2 opacity-50" />
        <p className="text-sm">Drop PDF, DOCX, or TXT files here</p>
      </div>

      <div className="space-y-3">
        {filtered.map(d => (
          <GlassCard key={d.id} className="p-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-300">
                <FileText className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-white truncate">{d.name || d.file_path.split('/').pop()}</div>
                <div className="text-xs text-zinc-500">{agentName(d.agent_id)} · {d.chunk_count} chunks · retries {d.retry_count || 0}</div>
                {d.last_error && (
                  <div className="text-[11px] text-amber-400/80 truncate max-w-[42rem]" title={d.last_error}>
                    last error: {d.last_error}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <Badge variant={docBadge(d.status)}>
                {d.status === 'indexing' && <Loader2 className="w-2.5 h-2.5 animate-spin inline mr-1" />}
                {d.status}
              </Badge>
              {(d.status === 'failed' || d.status === 'pending') && (
                <button onClick={() => retryOne(d.id)} className="px-2 py-1 rounded-lg border border-white/10 text-xs text-zinc-300 hover:bg-white/5">
                  Retry
                </button>
              )}
              <button onClick={() => del(d.id)} className="p-2 rounded-lg hover:bg-red-500/10 text-red-400 transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </GlassCard>
        ))}
        {filtered.length === 0 && (
          <GlassCard className="p-12 text-center">
            <p className="text-sm text-zinc-500">No documents found.</p>
          </GlassCard>
        )}
      </div>
    </div>
  );
}
