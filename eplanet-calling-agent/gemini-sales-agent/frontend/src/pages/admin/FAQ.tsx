import { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { ChevronDown, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';

const FAQ_ITEMS = [
  {
    q: 'How do I make a test call?',
    a: 'Register Zoiper with user 1000 / password 1000pass against your LAN IP (shown on Dashboard). Dial 701, 702, or 703. Use headphones and disable Zoiper echo cancellation for best results.',
  },
  {
    q: 'Why does the agent stay silent at the start?',
    a: 'The bridge sends an AUTO_GREETING when audio connects so Gemini speaks first. If silence persists, check gemini_bridge logs and GEMINI_API_KEY. Ensure bridge and platform containers are healthy.',
  },
  {
    q: 'What are extensions 701, 702, and 703?',
    a: '701 = Maya (lead qualification), 702 = Aria (sales), 703 = Sam (support FAQ). Each maps to an agent via inbound_extension in the database and Asterisk dialplan Stasis routing.',
  },
  {
    q: 'How does knowledge base (RAG) work?',
    a: 'Upload PDF/DOCX/TXT in Documents for an agent. Celery chunks and embeds text into Pinecone (namespace agent-{id}). At call start, top chunks preload into the agent prompt. During calls, search_knowledge_base tool retrieves more.',
  },
  {
    q: 'What is the Voice Master Prompt?',
    a: 'A global prompt prepended to every agent system prompt. It enforces human-like phone behavior: polite tone, no dead air during tool calls, brief answers, and use of preloaded KB at call start. See Help & Docs for full text.',
  },
  {
    q: 'Why is my transcript split into many fragments?',
    a: 'Older sessions may show fragmented rows. New calls buffer transcription until each turn completes, storing full paragraphs. The session page merges legacy data automatically.',
  },
  {
    q: 'Can I use the browser mic instead of Zoiper?',
    a: 'Not in v1. This stack is SIP-only: Zoiper (or any SIP phone) on your LAN. The admin UI is for management, not browser calling.',
  },
  {
    q: 'Why only one call at a time?',
    a: 'The bridge handles one concurrent Gemini Live session per instance (v1). Hang up before placing another call.',
  },
  {
    q: 'Documents stuck on "indexing"?',
    a: 'Check PINECONE_API_KEY in .env, run make bootstrap, and inspect docker logs aura_celery. Index aura-knowledge is auto-created on first use.',
  },
  {
    q: 'How do I add a new agent and extension?',
    a: 'Admin → Agents → New Agent. Set inbound extension (e.g. 704), prompt, tools. Add matching exten => 704,1,Stasis(gemini-agent,slug) in asterisk/extensions.conf and restart asterisk.',
  },
  {
    q: 'Where are call summaries generated?',
    a: 'Automatically when a SIP call ends (post_call service). You can also click Re-summarize on any session. Summaries use merged conversation turns, not raw fragments.',
  },
  {
    q: 'What tools can agents use during calls?',
    a: 'create_lead, search_contacts, create_note, update_lead_status, search_knowledge_base — enabled per agent in the Agents page. The bridge forwards tool calls to the platform API.',
  },
  {
    q: 'Zoiper won\'t register — what to check?',
    a: 'Same Wi-Fi as the server, use EXTERNAL_IP from Dashboard (not 127.0.0.1 unless Zoiper is on the same machine), port 5060 UDP open, credentials 1000/1000pass, PCMU codec.',
  },
  {
    q: 'How is my data stored?',
    a: 'PostgreSQL: agents, sessions, messages, tool_calls, leads, documents metadata. Pinecone: vector embeddings per agent. Files on disk in uploads volume, indexed by Celery.',
  },
];

function FaqItem({ q, a, open, onToggle }: { q: string; a: string; open: boolean; onToggle: () => void }) {
  return (
    <GlassCard className="overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-4 p-4 text-left hover:bg-white/[0.02] transition-colors"
      >
        <span className="text-sm font-medium text-zinc-200">{q}</span>
        <ChevronDown className={cn('w-4 h-4 text-zinc-500 shrink-0 transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <p className="px-4 pb-4 text-sm text-zinc-400 leading-relaxed border-t border-white/5 pt-3">{a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
  );
}

export default function FAQ() {
  const [openIdx, setOpenIdx] = useState<number | null>(0);

  return (
    <div className="p-6 lg:p-8 max-w-3xl">
      <PageHeader
        title="FAQ"
        subtitle="Quick answers about calling, agents, RAG, and troubleshooting"
      />

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center gap-3 p-4 rounded-2xl border border-violet-500/20 bg-violet-500/5 mb-8"
      >
        <HelpCircle className="w-5 h-5 text-violet-400 shrink-0" />
        <p className="text-sm text-zinc-400">
          Need architecture deep-dives? See <Link to="/admin/docs" className="text-violet-400 hover:underline">Help & Docs</Link> for diagrams, master prompt details, and setup guides.
        </p>
      </motion.div>

      <div className="space-y-3">
        {FAQ_ITEMS.map((item, i) => (
          <FaqItem
            key={item.q}
            q={item.q}
            a={item.a}
            open={openIdx === i}
            onToggle={() => setOpenIdx(openIdx === i ? null : i)}
          />
        ))}
      </div>
    </div>
  );
}
