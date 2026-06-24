import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Phone, Server, Database, Bot, FileText, Zap, Radio, Layers,
  ArrowRight, ExternalLink,
} from 'lucide-react';
import { PageHeader, GlassCard, Badge } from '@/src/components/admin/theme';
import { MermaidDiagram } from '@/src/components/admin/docs/MermaidDiagram';
import { DocsSection, InfoGrid, FlowStep, CodeBlock, Pill } from '@/src/components/admin/docs/DocsSection';
import { useAuth } from '@/src/auth/AuthContext';
import { API_BASE } from '@/src/lib/api';

const NAV_SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'call-flow', label: 'Call flow' },
  { id: 'outbound', label: 'Outbound calls' },
  { id: 'services', label: 'Docker services' },
  { id: 'master-prompt', label: 'Master prompt' },
  { id: 'agents', label: 'Agents & routing' },
  { id: 'rag', label: 'Knowledge base' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'tools', label: 'Tools' },
  { id: 'setup', label: 'Setup guide' },
  { id: 'env', label: 'Environment' },
  { id: 'structure', label: 'Project structure' },
];

const ARCHITECTURE_CHART = `
flowchart TB
  subgraph client [Your LAN]
    Zoiper[Zoiper SIP Phone]
  end
  subgraph docker [Docker Compose Stack]
    FE[aura_frontend :80]
    PL[aura_platform :8000]
    PG[(PostgreSQL)]
    RD[(Redis)]
    CE[aura_celery]
    AS[asterisk :5060]
    BR[gemini_bridge]
    PC[(Pinecone Cloud)]
  end
  subgraph cloud [Google Cloud]
    GL[Gemini Live API]
    EM[gemini-embedding-001]
  end
  Zoiper -->|SIP UDP 5060| AS
  AS -->|Stasis + RTP| BR
  BR -->|WebSocket audio| GL
  BR -->|POST /internal/calls| PL
  PL --> PG
  PL --> RD
  CE --> PG
  CE --> EM
  CE --> PC
  PL -->|RAG query| PC
  FE -->|/api proxy| PL
`;

const CALL_SEQUENCE = `
sequenceDiagram
  participant Caller as Zoiper Caller
  participant AST as Asterisk
  participant BR as gemini_bridge
  participant PL as Platform API
  participant GM as Gemini Live
  participant PC as Pinecone

  Caller->>AST: Dial ext 701
  AST->>BR: StasisStart + RTP
  BR->>PL: POST /internal/calls/start
  PL->>PC: Preload KB chunks
  PL-->>BR: agent config + system prompt
  BR->>GM: Connect Live session
  BR->>GM: AUTO_GREETING turn
  GM-->>Caller: Agent speaks first
  loop Conversation
    Caller->>BR: RTP audio in
    BR->>GM: PCM16 16kHz stream
    GM-->>BR: Audio + transcription
    opt Tool needed
      GM->>BR: function_call
      BR->>PL: POST /internal/calls/tool
      PL->>PC: search_knowledge_base
      PL-->>BR: tool result
      BR->>GM: function_response
    end
    BR->>PL: POST transcript per turn
  end
  Caller->>AST: Hangup
  BR->>PL: POST /internal/calls/end
  PL->>PL: Auto summary + lead capture
`;

const RAG_FLOW = `
flowchart LR
  UP[Upload PDF/DOCX/TXT] --> CEL[Celery worker]
  CEL --> CH[Chunk text]
  CH --> EM[Embed gemini-embedding-001]
  EM --> PIN[Upsert Pinecone agent-N]
  CALL[Call starts] --> PRE[Preload top-K chunks]
  PRE --> PROMPT[Inject into system prompt]
  LIVE[During call] --> TOOL[search_knowledge_base tool]
  TOOL --> PIN
  PIN --> AGENT[Agent answers in speech]
`;

const MASTER_PROMPT_TEXT = `You are on a live phone call. Speak like a real human call-center professional:
- Warm, polite, empathetic, and professional — never robotic or list-like
- Use natural pacing; brief pauses between thoughts
- Occasional natural fillers when thinking ("um", "let me see", "one moment") — sparingly
- Keep answers concise; one or two sentences unless the caller asks for detail
- Listen fully before responding; never interrupt

Engagement during lookups (critical — no dead air):
- BEFORE calling any tool, say a brief natural line out loud first
- Never go silent while a tool is running
- AFTER tool results, answer in plain spoken language
- At call start, use preloaded knowledge context immediately`;

export default function HelpDocs() {
  const { token } = useAuth();
  const [sipInfo, setSipInfo] = useState<{ sip_server?: string; external_ip?: string }>({});

  useEffect(() => {
    fetch(`${API_BASE}/api/system/info`)
      .then(r => r.json())
      .then(setSipInfo)
      .catch(() => {});
  }, [token]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Help & Documentation"
        subtitle="Architecture, flows, master prompt, setup — everything about Aura Call Center"
        action={
          <Link to="/admin/faq" className="text-xs text-violet-400 hover:underline flex items-center gap-1">
            FAQ <ArrowRight className="w-3 h-3" />
          </Link>
        }
      />

      <div className="flex flex-col lg:flex-row gap-8">
        {/* Sticky nav */}
        <nav className="lg:w-48 shrink-0">
          <div className="lg:sticky lg:top-6 space-y-1">
            {NAV_SECTIONS.map(s => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className="block px-3 py-2 rounded-lg text-xs font-medium text-zinc-500 hover:text-violet-300 hover:bg-white/5 transition-colors"
              >
                {s.label}
              </a>
            ))}
          </div>
        </nav>

        <div className="flex-1 min-w-0 space-y-14">
          <DocsSection id="overview" title="Platform overview" subtitle="AI phone call center on your LAN">
            <GlassCard className="p-5 mb-4">
              <p className="text-sm text-zinc-300 leading-relaxed">
                <strong className="text-white">Aura Call Center</strong> connects a SIP softphone (Zoiper) to{' '}
                <Pill color="cyan">Google Gemini Live</Pill> for real-time voice AI. Each extension (701–703) routes to a
                different agent with its own prompt, voice, tools, and knowledge base. <strong className="text-white">Outbound</strong> cold
                calls are placed from <Link to="/admin/outbound" className="text-orange-400 hover:underline">Outbound Calls</Link> in the CRM
                (mobile Zoiper as ext 1001 receives the call). The admin UI manages agents, documents, sessions, leads, and CRM.
              </p>
            </GlassCard>
            <InfoGrid items={[
              { label: 'Admin UI', value: 'http://localhost (port 80)' },
              { label: 'API health', value: 'http://localhost/api/system/info', mono: true },
              { label: 'SIP server', value: sipInfo.sip_server || sipInfo.external_ip || 'See Dashboard', mono: true },
              { label: 'Default login', value: 'admin@aura.ai / changeme123' },
            ]} />
          </DocsSection>

          <DocsSection id="architecture" title="System architecture" subtitle="How components connect">
            <MermaidDiagram chart={ARCHITECTURE_CHART} />
            <p className="text-xs text-zinc-500 mt-3">
              Only <code className="text-violet-400">gemini_bridge</code> subscribes to Asterisk ARI app{' '}
              <code className="text-violet-400">gemini-agent</code>. The platform never handles RTP directly.
            </p>
          </DocsSection>

          <DocsSection id="outbound" title="Outbound calls (CRM)" subtitle="Dial Riley from the admin — phone receives the call">
            <GlassCard className="p-5 space-y-3 text-sm text-zinc-300">
              <ol className="list-decimal list-inside space-y-2 text-zinc-400">
                <li>Register mobile Zoiper as extension <strong className="text-white">1001</strong> to your SIP server IP (Dashboard).</li>
                <li>Admin → <Link to="/admin/outbound" className="text-orange-400 hover:underline">Outbound Calls</Link> → Riley → <strong className="text-white">Dial now</strong>.</li>
                <li>Answer on the phone — Gemini places the cold call (AUTO_GREETING opens).</li>
                <li>Optional: pick a <Link to="/admin/leads" className="text-violet-400 hover:underline">Lead</Link> for CRM context, or use the <strong className="text-white">Call</strong> button on a lead row.</li>
                <li>Review <Link to="/admin/sessions" className="text-violet-400 hover:underline">Sessions</Link> for transcript and call_disposition output.</li>
              </ol>
              <p className="text-xs text-zinc-500 pt-2 border-t border-white/5">
                Manage Riley like inbound agents: <Link to="/admin/agents" className="text-violet-400">Agents</Link>,{' '}
                <Link to="/admin/documents" className="text-violet-400">Knowledge base</Link>, prompts, tools.
              </p>
            </GlassCard>
          </DocsSection>

          <DocsSection id="call-flow" title="End-to-end call flow" subtitle="From dial to summary">
            <MermaidDiagram chart={CALL_SEQUENCE} />
            <div className="mt-6 space-y-0">
              <FlowStep step={1} icon={Phone} title="Caller dials extension" description="Zoiper sends SIP INVITE to Asterisk. Dialplan matches 701/702/703 and enters Stasis(gemini-agent, agent-slug)." delay={0} />
              <FlowStep step={2} icon={Server} title="Bridge creates media path" description="Bridge creates mixing bridge + ExternalMedia channel. RTP flows on port 40000 between Asterisk and bridge." delay={0.05} />
              <FlowStep step={3} icon={Database} title="Platform session + KB preload" description="POST /internal/calls/start resolves agent, preloads Pinecone chunks into system prompt, creates DB session." delay={0.1} />
              <FlowStep step={4} icon={Radio} title="Gemini Live connects" description="Bridge opens WebSocket to Gemini with agent config, tools, and merged system instruction. AUTO_GREETING triggers first speech." delay={0.15} />
              <FlowStep step={5} icon={Bot} title="Conversation loop" description="Audio streams both ways. Transcription buffered per turn. Tool calls proxy to platform. Transcripts saved to PostgreSQL." delay={0.2} />
              <FlowStep step={6} icon={Zap} title="Call ends → post-processing" description="Gemini text model generates prose summary (sessions.summary), structured JSON outputs (Outputs page), session note (Notes page), and optional Lead row for qualification agents. Use Session Detail → Generate all to re-run." delay={0.25} />
            </div>
          </DocsSection>

          <DocsSection id="services" title="Docker services" subtitle="8 containers orchestrated by docker-compose">
            <div className="overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 bg-white/[0.02]">
                    <th className="text-left p-3 text-xs font-semibold text-zinc-500">Container</th>
                    <th className="text-left p-3 text-xs font-semibold text-zinc-500">Port</th>
                    <th className="text-left p-3 text-xs font-semibold text-zinc-500">Role</th>
                  </tr>
                </thead>
                <tbody className="text-zinc-300">
                  {[
                    ['aura_frontend', '80', 'React admin UI + nginx API proxy'],
                    ['aura_platform', '8000', 'FastAPI — agents, sessions, CRM, internal bridge API'],
                    ['aura_postgres', 'internal', 'PostgreSQL 16 — all relational data'],
                    ['aura_redis', 'internal', 'Celery message broker'],
                    ['aura_celery', 'internal', 'Async document indexing worker'],
                    ['aura_platform_init', 'one-shot', 'DB migration + bootstrap seed'],
                    ['asterisk', '5060/udp, 8088', 'SIP registration, dialplan, ARI, RTP'],
                    ['gemini_bridge', 'internal', 'ARI websocket + RTP ↔ Gemini Live'],
                  ].map(([c, p, r]) => (
                    <tr key={c} className="border-b border-white/5">
                      <td className="p-3 font-mono text-xs text-violet-300">{c}</td>
                      <td className="p-3 font-mono text-xs">{p}</td>
                      <td className="p-3 text-xs text-zinc-400">{r}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </DocsSection>

          <DocsSection id="master-prompt" title="Voice master prompt" subtitle="Prepended to every agent — defines phone behavior">
            <GlassCard className="p-5 border-violet-500/20 bg-gradient-to-br from-violet-600/10 to-transparent mb-4">
              <Badge variant="default">VOICE_MASTER_PROMPT</Badge>
              <div className="mt-3">
                <CodeBlock>{MASTER_PROMPT_TEXT}</CodeBlock>
              </div>
            </GlassCard>
            <div className="grid sm:grid-cols-2 gap-3 text-sm">
              <GlassCard className="p-4">
                <div className="font-semibold text-white mb-1">+ Agent role prompt</div>
                <p className="text-xs text-zinc-400">Each agent has system_prompt_template (persona, goals, Trangotech context).</p>
              </GlassCard>
              <GlassCard className="p-4">
                <div className="font-semibold text-white mb-1">+ Preloaded KB block</div>
                <p className="text-xs text-zinc-400">Top Pinecone chunks injected at call start via preload_agent_context().</p>
              </GlassCard>
              <GlassCard className="p-4">
                <div className="font-semibold text-white mb-1">AUTO_GREETING</div>
                <p className="text-xs text-zinc-400">Bridge sends a client turn so Gemini speaks first — no awkward silence.</p>
              </GlassCard>
              <GlassCard className="p-4">
                <div className="font-semibold text-white mb-1">Source file</div>
                <p className="text-xs text-zinc-400 font-mono">backend/services/live_config.py</p>
              </GlassCard>
            </div>
          </DocsSection>

          <DocsSection id="agents" title="Agents & SIP routing" subtitle="Extension → agent mapping">
            <div className="overflow-x-auto rounded-xl border border-white/10 mb-4">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 bg-white/[0.02]">
                    <th className="p-3 text-left text-xs text-zinc-500">Ext</th>
                    <th className="p-3 text-left text-xs text-zinc-500">Agent</th>
                    <th className="p-3 text-left text-xs text-zinc-500">Slug</th>
                    <th className="p-3 text-left text-xs text-zinc-500">Purpose</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['701', 'Maya — Lead Qualifier', 'lead-qualifier', 'Collect lead info → create_lead'],
                    ['702', 'Aria — Sales', 'trangotech-sales', 'Sales consult + pricing from KB'],
                    ['703', 'Sam — Support', 'support-faq', 'FAQ from KB only'],
                    ['600', '—', '—', 'Echo test (mic/speaker check)'],
                    ['700', '—', 'fallback', 'First active agent (legacy)'],
                  ].map(([ext, name, slug, purpose]) => (
                    <tr key={ext} className="border-b border-white/5">
                      <td className="p-3 font-mono text-violet-300">{ext}</td>
                      <td className="p-3 text-zinc-200">{name}</td>
                      <td className="p-3 font-mono text-xs text-zinc-500">{slug}</td>
                      <td className="p-3 text-xs text-zinc-400">{purpose}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <CodeBlock>{`# asterisk/extensions.conf
exten => 701,1,Stasis(gemini-agent,lead-qualifier)
 same => n,Hangup()`}</CodeBlock>
          </DocsSection>

          <DocsSection id="rag" title="Knowledge base (RAG)" subtitle="Pinecone + Gemini embeddings">
            <MermaidDiagram chart={RAG_FLOW} />
            <div className="mt-4 space-y-2 text-sm text-zinc-400">
              <p><Pill color="emerald">Index</Pill> aura-knowledge (768 dims, cosine, auto-created)</p>
              <p><Pill color="cyan">Namespace</Pill> agent-{'{id}'} per agent + global fallback</p>
              <p><Pill color="violet">Embedding</Pill> gemini-embedding-001 with L2 normalization</p>
              <p><Pill color="amber">Worker</Pill> aura_celery processes uploads from Documents page</p>
            </div>
          </DocsSection>

          <DocsSection id="sessions" title="Sessions & transcripts" subtitle="How call data is stored and displayed">
            <GlassCard className="p-5 space-y-3 text-sm text-zinc-300">
              <p><strong className="text-white">Storage:</strong> Each call creates a Session row. Messages store merged turn paragraphs (user/model). Tool calls log name, params, result, duration.</p>
              <p><strong className="text-white">Bridge buffering:</strong> Streaming transcription fragments accumulate until turn_complete, then one POST per turn.</p>
              <p><strong className="text-white">Legacy merge:</strong> session_timeline.py merges old fragmented rows on read for clean UI and summaries.</p>
              <p><strong className="text-white">Timeline UI:</strong> Conversation paragraphs + inline tool cards + formatted outputs (lead capture fields).</p>
            </GlassCard>
          </DocsSection>

          <DocsSection id="tools" title="Agent tools" subtitle="Function calls during live calls">
            <div className="grid gap-3">
              {[
                ['search_knowledge_base', 'Query Pinecone for agent KB chunks', 'Sam, Aria, Maya'],
                ['create_lead', 'Save lead to CRM from conversation', 'Maya, Aria'],
                ['create_note', 'Attach note to session/lead/contact', 'All'],
                ['search_contacts', 'Look up contact directory', 'Optional'],
                ['update_lead_status', 'Change lead pipeline status', 'CRM workflows'],
              ].map(([name, desc, agents]) => (
                <GlassCard key={name} className="p-4 flex flex-wrap items-start gap-3">
                  <code className="text-xs text-violet-300 font-mono">{name}</code>
                  <span className="text-sm text-zinc-400 flex-1">{desc}</span>
                  <span className="text-[10px] text-zinc-600">Used by: {agents}</span>
                </GlassCard>
              ))}
            </div>
          </DocsSection>

          <DocsSection id="setup" title="Setup guide" subtitle="From zero to first call">
            <CodeBlock>{`# 1. Configure environment
cp .env.example .env
# Set GEMINI_API_KEY, PINECONE_API_KEY, BRIDGE_INTERNAL_TOKEN

# 2. Start stack
./start.sh up -d --build
./scripts/check.sh

# 3. Seed agents + RAG (idempotent)
make bootstrap

# 4. Configure Zoiper
# User: 1000 / Pass: 1000pass
# Server: EXTERNAL_IP from Dashboard
# Port: 5060 UDP, codec PCMU

# 5. Test
# Dial 600 (echo), then 701/702/703
# View session in Admin → Call Sessions`}</CodeBlock>
          </DocsSection>

          <DocsSection id="env" title="Key environment variables" subtitle="Root .env shared by all services">
            <InfoGrid items={[
              { label: 'GEMINI_API_KEY', value: 'Gemini Live voice + embeddings', mono: true },
              { label: 'PINECONE_API_KEY', value: 'Vector DB for RAG', mono: true },
              { label: 'PINECONE_INDEX_NAME', value: 'Default: aura-knowledge', mono: true },
              { label: 'BRIDGE_INTERNAL_TOKEN', value: 'Bridge ↔ platform auth header', mono: true },
              { label: 'JWT_SECRET_KEY', value: 'Admin login tokens', mono: true },
              { label: 'ADMIN_EMAIL / ADMIN_PASSWORD', value: 'Bootstrap admin user', mono: true },
              { label: 'RTP_PORT', value: '40000 — Asterisk ExternalMedia', mono: true },
              { label: 'AUTO_GREETING', value: 'Empty = use default greeting prompt', mono: true },
            ]} />
          </DocsSection>

          <DocsSection id="structure" title="Project structure" subtitle="Repository layout">
            <CodeBlock>{`astrersik/
├── .env / .env.example / .host.env
├── docker-compose.yml
├── start.sh / Makefile / scripts/check.sh
├── asterisk/              # pjsip, extensions 701-703, ARI
├── bridge/app/main.py     # ARI + RTP + Gemini + transcript buffer
└── eplanet-calling-agent/gemini-sales-agent/
    ├── backend/
    │   ├── routers/internal_bridge.py  # Bridge API
    │   ├── services/live_config.py     # Master prompt + KB preload
    │   ├── services/session_timeline.py
    │   └── services/rag_service.py
    └── frontend/            # React admin (this UI)`}</CodeBlock>
            <a
              href="https://github.com"
              className="inline-flex items-center gap-1 mt-4 text-xs text-zinc-500 hover:text-violet-400"
              onClick={e => e.preventDefault()}
            >
              <FileText className="w-3.5 h-3.5" />
              Full README at repository root (README.md)
              <ExternalLink className="w-3 h-3" />
            </a>
          </DocsSection>

          <GlassCard className="p-6 text-center border-violet-500/20">
            <Layers className="w-8 h-8 text-violet-400 mx-auto mb-3" />
            <p className="text-sm text-zinc-300 mb-2">Still stuck?</p>
            <Link to="/admin/faq" className="text-violet-400 hover:underline text-sm font-medium">
              Browse the FAQ →
            </Link>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
