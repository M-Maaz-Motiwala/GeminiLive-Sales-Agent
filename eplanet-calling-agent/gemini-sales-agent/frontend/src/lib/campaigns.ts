import { API_BASE, apiFetch, apiFetchList } from '@/src/lib/api';

export type CampaignProgress = {
  total: number;
  pending: number;
  dialing: number;
  completed: number;
  failed: number;
  skipped: number;
  percent_done: number;
  active_slots: number;
  max_parallel: number | null;
  inter_call_delay_sec?: number;
  agent_ids?: number[];
  agents_in_cooldown?: number;
  scheduled_at?: string | null;
  runner_active: boolean;
};

export type Campaign = {
  id: number;
  name: string;
  agent_id: number;
  agent_ids?: number[];
  organization_id?: number | null;
  organization_name?: string | null;
  inter_call_delay_sec?: number;
  status: string;
  description?: string | null;
  lead_count: number;
  created_at: string;
  updated_at?: string;
  progress?: CampaignProgress;
  campaign_leads?: CampaignLeadRow[];
};

export type CampaignLeadRow = {
  id: number;
  lead_id: number | null;
  endpoint: string | null;
  status: string;
  session_id: number | null;
  last_error: string | null;
  dialed_at: string | null;
  lead_name?: string | null;
  lead_phone?: string | null;
  lead_company?: string | null;
};

export function fetchCampaigns(token: string | null) {
  return apiFetchList<Campaign>('/api/campaigns', token);
}

export function fetchCampaign(token: string | null, id: number) {
  return apiFetch<Campaign>(`/api/campaigns/${id}`, token);
}

export function createCampaign(
  token: string | null,
  body: {
    name: string;
    agent_ids: number[];
    agent_id?: number;
    inter_call_delay_sec?: number;
    description?: string;
    endpoints?: string[];
    lead_ids?: number[];
  },
) {
  return apiFetch<Campaign>('/api/campaigns', token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function updateCampaign(
  token: string | null,
  id: number,
  body: { name?: string; description?: string; agent_id?: number },
) {
  return apiFetch<Campaign>(`/api/campaigns/${id}`, token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function deleteCampaign(token: string | null, id: number) {
  return apiFetch(`/api/campaigns/${id}`, token, { method: 'DELETE' });
}

export function addCampaignLeads(
  token: string | null,
  id: number,
  body: { endpoints?: string[]; lead_ids?: number[] },
) {
  return apiFetch(`/api/campaigns/${id}/leads`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function importCampaignCsv(token: string | null, id: number, file: File) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/api/campaigns/${id}/import-csv`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export function startCampaign(
  token: string | null,
  id: number,
  body: {
    max_parallel: number;
    inter_call_delay_sec?: number;
    start_at?: string | null;
  },
) {
  return apiFetch(`/api/campaigns/${id}/start`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function pauseCampaign(token: string | null, id: number) {
  return apiFetch(`/api/campaigns/${id}/pause`, token, { method: 'POST' });
}

export function stopCampaign(token: string | null, id: number) {
  return apiFetch(`/api/campaigns/${id}/stop`, token, { method: 'POST' });
}

export function resetCampaign(token: string | null, id: number) {
  return apiFetch<{ reset: number }>(`/api/campaigns/${id}/reset`, token, { method: 'POST' });
}

export function statusBadgeVariant(status: string): 'default' | 'success' | 'warn' | 'live' {
  if (status === 'running') return 'live';
  if (status === 'completed') return 'success';
  if (status === 'paused' || status === 'failed') return 'warn';
  return 'default';
}

export function leadStatusColor(status: string): string {
  switch (status) {
    case 'completed':
      return 'text-emerald-400';
    case 'dialing':
      return 'text-cyan-400';
    case 'failed':
      return 'text-red-400';
    case 'skipped':
      return 'text-zinc-500';
    default:
      return 'text-zinc-400';
  }
}
