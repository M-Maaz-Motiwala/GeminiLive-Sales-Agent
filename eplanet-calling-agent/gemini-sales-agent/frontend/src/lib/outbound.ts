import { apiFetch, apiFetchList } from '@/src/lib/api';

export type OutboundAgent = {
  id: number;
  name: string;
  slug: string;
  voice?: string;
  inbound_extension?: string | null;
};

export async function fetchOutboundAgents(token: string | null): Promise<OutboundAgent[]> {
  return apiFetchList('/api/outbound/agents', token);
}

export async function dialOutbound(
  token: string | null,
  body: { agent_id: number; lead_id?: number; endpoint?: string },
): Promise<{ status: string; endpoint: string; bridge?: { channel_id?: string } }> {
  return apiFetch('/api/outbound/dial', token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function dialBatch(
  token: string | null,
  body: { agent_id: number; endpoints?: string[]; lead_ids?: number[] },
): Promise<{ dialed: number; failed: number; results: any[] }> {
  return apiFetch('/api/outbound/dial/batch', token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function fetchOutboundStatus(token: string | null) {
  return apiFetch<{
    outbound_mode: string;
    call_window_allowed: boolean;
    bridge?: { active_calls?: number; max_concurrent?: number };
  }>('/api/outbound/status', token);
}

/** Lab default when lead has no phone — matches OUTBOUND_LAB_ENDPOINT */
export const DEFAULT_LAB_ENDPOINT = 'PJSIP/1001';
