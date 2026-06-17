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

export type DialTrackerState = {
  channel_id: string;
  dial_phase: string;
  label: string;
  outcome?: string | null;
  terminal?: boolean;
  endpoint?: string;
  session_id?: number;
  session_status?: string;
  prospect_answered?: boolean;
  hangup_cause_txt?: string | null;
};

export async function fetchDialStatus(
  token: string | null,
  channelId: string,
): Promise<DialTrackerState> {
  return apiFetch(`/api/outbound/dial-status/${encodeURIComponent(channelId)}`, token);
}

export async function dialOutbound(
  token: string | null,
  body: { agent_id: number; lead_id?: number; endpoint?: string; connect_experience?: 'auto_greeting' | 'comfort_tone' },
): Promise<{ status: string; endpoint: string; bridge?: { channel_id?: string; dial_phase?: string; label?: string } }> {
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

/** Persist active outbound dial across CRM navigation (same browser tab). */
export const OUTBOUND_DIAL_STORAGE_KEY = 'aura_outbound_active_dial';

export function loadStoredActiveDial(): Pick<DialTrackerState, 'channel_id' | 'endpoint'> | null {
  try {
    const raw = sessionStorage.getItem(OUTBOUND_DIAL_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.channel_id) return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

export function storeActiveDial(dial: DialTrackerState) {
  sessionStorage.setItem(
    OUTBOUND_DIAL_STORAGE_KEY,
    JSON.stringify({ channel_id: dial.channel_id, endpoint: dial.endpoint }),
  );
}

export function clearStoredActiveDial() {
  sessionStorage.removeItem(OUTBOUND_DIAL_STORAGE_KEY);
}

export async function fetchOutboundStatus(token: string | null) {
  return apiFetch<{
    outbound_mode: string;
    call_window_allowed: boolean;
    bridge?: { active_calls?: number; max_concurrent?: number; calls?: any[] };
    active_dials?: DialTrackerState[];
  }>('/api/outbound/status', token);
}

/** Lab default when lead has no phone — matches OUTBOUND_LAB_ENDPOINT */
export const DEFAULT_LAB_ENDPOINT = 'PJSIP/1001';
