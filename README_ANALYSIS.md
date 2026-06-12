# 📋 Complete Codebase Analysis - Index & Summary

## 📁 Documents Created

This analysis consists of 4 comprehensive documents. Choose based on your needs:

### 1. **CODEBASE_ANALYSIS.md** (Primary - Start Here)
**Length**: ~8,000 words | **Format**: Complete structured analysis
- ✓ Architecture overview (services, containers)
- ✓ Inbound flow (SIP → Gemini → Agent)
- ✓ Outbound architecture (Campaign dialing)
- ✓ What was reused vs new
- ✓ Tool calling mechanism (step-by-step)
- ✓ Service interaction map
- ✓ Concurrency & capacity analysis
- ✓ 12+ enhancement recommendations
- ✓ Deployment roadmap

**Best for**: Getting complete picture, understanding architecture decisions

### 2. **QUICK_REFERENCE.md** (Reference Sheet)
**Length**: ~2,500 words | **Format**: Visual diagrams + quick facts
- ✓ Tool calling flow (visual diagram)
- ✓ Execution timeline (parallel vs sequential)
- ✓ Concurrency limits explained
- ✓ Call window & DNC rules
- ✓ Agent type matrix
- ✓ Status lifecycle diagrams
- ✓ Database relationships
- ✓ Code reuse summary (85%)
- ✓ Debugging checklist

**Best for**: Quick lookups, visual learners, troubleshooting

### 3. **TECHNICAL_DEEP_DIVE.md** (Implementation Details)
**Length**: ~5,000 words | **Format**: Code examples + flow walkthroughs
- ✓ Native tool calling architecture (why Gemini's approach is better)
- ✓ Tool execution under the hood (5 phases)
- ✓ Concurrency architecture (detailed)
- ✓ Bridge capacity & RTP ports
- ✓ Campaign runner parallelization logic
- ✓ Connection pooling levels
- ✓ Call window validation (timezone-aware)
- ✓ Token metering & pricing
- ✓ Performance benchmarks
- ✓ Debugging & monitoring queries

**Best for**: Developers, DevOps, performance tuning

### 4. **This File** (Navigation)
Quick index to find what you need

---

## 🎯 Quick Answers to Your Questions

### Q1: "How was outbound built on inbound?"
**Answer**: 85% code reuse. Same GeminiLiveSession, tool calling, RTP bridge, message persistence. New: Campaign model, runner loop, endpoint resolver, outbound policy.

**See**: CODEBASE_ANALYSIS.md → Part 2 & 3, or QUICK_REFERENCE.md → "Why 85% Code Reuse"

### Q2: "How is tool calling implemented?"
**Answer**: Gemini natively detects tool needs. Your code dispatches tools in parallel via `asyncio.gather()`, persists results, sends back to Gemini. Gemini decides next action.

**See**: CODEBASE_ANALYSIS.md → Part 5, or TECHNICAL_DEEP_DIVE.md → Section 1 & 2

### Q3: "Where is each service used?"
**Answer**: Service Interaction Map shows every service + caller.

**See**: CODEBASE_ANALYSIS.md → Part 6 (table format), or TECHNICAL_DEEP_DIVE.md → Concurrency section

### Q4: "How many calls in parallel? 5 concurrent limit—why?"
**Answer**: `max_concurrent_outbound = 5` in config. RTP ports (51 available) are physical limit. Bridge capacity + DB connections scale at 5 easily. To 20+, increase config + monitor pooling.

**See**: CODEBASE_ANALYSIS.md → Part 7, or QUICK_REFERENCE.md → "Concurrency Limits Explained"

### Q5: "What can we add?"
**Answer**: 12 recommendations: Multi-bridge load balancing, campaign persistence, real-time dashboards, tool caching, recording, multi-agent handoff, IVR routing, and more.

**See**: CODEBASE_ANALYSIS.md → Part 8 (12 detailed recommendations)

---

## 📊 Key Facts at a Glance

| Aspect | Value | Reference |
|--------|-------|-----------|
| **Code Reuse** | 85% | QUICK_REFERENCE.md |
| **Max Concurrent Outbound** | 5 | config.py / CODEBASE_ANALYSIS Part 7 |
| **Max RTP Ports** | 51 | docker-compose.yml (10000-10050) |
| **Tool Call Parallelization** | Yes (asyncio.gather) | TECHNICAL_DEEP_DIVE Section 2 |
| **Typical Tool Call Latency** | 50-200ms | TECHNICAL_DEEP_DIVE Section 6 |
| **Parallel Multi-Tool Time** | Max of N tools | QUICK_REFERENCE.md (parallel timeline) |
| **Campaign Poll Frequency** | Every 2 seconds | campaign_runner.py (POLL_SEC=2.0) |
| **DB Pool Size** | 20 connections | SQLAlchemy default |
| **Audio TPS (tokens/sec)** | ~25 | token_meter.py |
| **Call Window** | Timezone-aware 9-6 | outbound_policy.py |
| **Post-Call Processing** | Async (non-blocking) | post_call.py |
| **Agent Types (Outbound)** | outbound_sales | db/models.py |
| **Enabled Tools per Agent** | Configurable | agent_config.enabled_tools |

---

## 🔍 Detailed Topic Lookup

### Architecture & Design
- High-level architecture: **CODEBASE_ANALYSIS Part 1**
- Inbound flow: **CODEBASE_ANALYSIS Part 2**
- Outbound flow: **CODEBASE_ANALYSIS Part 3**
- Service interactions: **CODEBASE_ANALYSIS Part 6**

### Tool Calling
- Overview: **CODEBASE_ANALYSIS Part 5**
- Detailed implementation: **TECHNICAL_DEEP_DIVE Section 1 & 2**
- Execution timeline: **QUICK_REFERENCE.md**
- Debugging: **TECHNICAL_DEEP_DIVE Section 7**

### Concurrency & Performance
- Limits & capacity: **CODEBASE_ANALYSIS Part 7**
- Campaign parallelization: **TECHNICAL_DEEP_DIVE Section 3**
- Connection pooling: **TECHNICAL_DEEP_DIVE Section 3**
- Benchmarks: **TECHNICAL_DEEP_DIVE Section 6**

### Outbound Specific
- Architecture: **CODEBASE_ANALYSIS Part 3**
- Campaign runner: **QUICK_REFERENCE.md** (visual)
- Campaign runner code: **TECHNICAL_DEEP_DIVE Section 3**
- Call window policy: **TECHNICAL_DEEP_DIVE Section 4**
- Endpoint resolver: **QUICK_REFERENCE.md** (Debugging)

### Database & Persistence
- Models & relationships: **QUICK_REFERENCE.md** (Database Relationships)
- Token metering: **TECHNICAL_DEEP_DIVE Section 5**
- Session lifecycle: **QUICK_REFERENCE.md** (Session & Campaign Lead Status)

### Scaling & Improvements
- Scaling recommendations: **CODEBASE_ANALYSIS Part 9**
- Specific enhancements: **CODEBASE_ANALYSIS Part 8** (12 recommendations)
- Performance tuning: **TECHNICAL_DEEP_DIVE Section 6**

---

## 📋 File-by-File Reference

### Platform (FastAPI)
| File | Purpose | Relation |
|------|---------|----------|
| `main.py` | App entry + router setup | All routers mounted here |
| `routers/sessions.py` | Session query/list API | Inbound & outbound queries |
| `routers/calls.py` | Active calls, hangup | Uses session_manager |
| `routers/outbound.py` | Dial API | Uses outbound_dialer |
| `routers/campaigns.py` | Campaign CRUD | Uses campaign_runner, CSV parser |
| `routers/agents.py` | Agent management | Agent config (enabled_tools, type) |
| `services/gemini_live.py` | Gemini session + tool dispatch | Core to inbound & outbound |
| `services/tool_executor.py` | Tool routing + dispatch | Called by gemini_live |
| `services/outbound_dialer.py` | Single dial logic | Called by routers & campaign_runner |
| `services/campaign_runner.py` | Background dialer loop | Async background task per campaign |
| `services/campaign_csv.py` | CSV parsing | Bulk lead import |
| `services/outbound_policy.py` | Call window + DNC | Validation before dial |
| `services/endpoint_resolver.py` | Phone → ARI endpoint | Resolves dial target |
| `services/post_call.py` | Post-call processing | Summarization, lead capture |
| `services/session_manager.py` | Active session registry | Lookup by session_id |
| `services/token_meter.py` | Token accounting | Per-session pricing |
| `services/rtp_bridge.py` | RTP receiver/sender | Inbound audio handling |
| `db/models.py` | SQLAlchemy ORM | All tables: Session, Message, ToolCall, Campaign, etc. |
| `db/database.py` | DB connection | AsyncSession factory |

### Bridge (Separate Service)
| File | Purpose | Relation |
|------|---------|----------|
| `app/main.py` | FastAPI + Asterisk ARI + Gemini Live | Receives stasisStart, manages RTP |
| `app/call_session.py` | Per-call state | Audio queues, RTP port, session ready event |

---

## 🚀 Next Steps Based on Your Goal

### Goal: "Scale to 20 concurrent calls"
1. Read: **CODEBASE_ANALYSIS Part 7 & 9**
2. Action: Increase `max_concurrent_outbound` to 20 in config.py
3. Action: Add PgBouncer for DB connection pooling
4. Monitor: Use health check endpoint to watch pool utilization
5. Optional: Deploy 2nd bridge instance + load balancer

### Goal: "Optimize tool calling"
1. Read: **TECHNICAL_DEEP_DIVE Section 2**
2. Insight: Already parallelized ✓
3. Consider: Tool call caching (CODEBASE_ANALYSIS Part 8, recommendation #6)
4. Monitor: Log tool_call durations to find bottlenecks

### Goal: "Understand campaign runner"
1. Read: **QUICK_REFERENCE.md** → Campaign Runner Loop
2. Deep-dive: **TECHNICAL_DEEP_DIVE Section 3** → Campaign Runner Parallelization
3. Key files: `services/campaign_runner.py`, `services/outbound_dialer.py`
4. Visualize: Campaign status lifecycle (QUICK_REFERENCE.md)

### Goal: "Build new features"
1. Read: **CODEBASE_ANALYSIS Part 8** (recommendations)
2. Choose feature (e.g., multi-bridge, call recording)
3. Reference: Existing patterns in code
4. Consider: Token cost, DB scaling impact

---

## 🔗 Key Code References

### Tool Calling
```
gemini_live.py
├─ GeminiLiveSession._build_config()           [Setup]
├─ GeminiLiveSession._receive_loop()           [Receive]
├─ GeminiLiveSession._handle_tool_call()       [Dispatch]
└─ GeminiLiveSession._persist_message()        [Persist]

tool_executor.py
├─ get_tool_declarations()                     [Filter]
└─ dispatch()                                  [Execute]

tools/crm_tools.py
├─ create_lead()                               [Impl]
├─ search_contacts()
├─ create_note()
└─ update_lead_status()

tools/rag_tools.py
└─ search_knowledge_base()                     [Impl]
```

### Outbound Dialing
```
routers/outbound.py
├─ POST /api/outbound/dial                     [Entry]
└─ POST /api/outbound/dial/batch

outbound_dialer.py
└─ dial_one()                                  [Core logic]

campaign_runner.py
├─ start_runner()                              [Start]
├─ _run_loop()                                 [Loop]
├─ _reconcile_active()                         [Check end]
└─ _fill_slots()                               [Dial next]

bridge_client.py
└─ originate_outbound()                        [HTTP to bridge]
```

### Campaign Management
```
routers/campaigns.py
├─ POST /api/campaigns                         [Create]
├─ POST /api/campaigns/{id}/start              [Start runner]
├─ POST /api/campaigns/{id}/upload             [CSV import]
└─ GET /api/campaigns/{id}                     [Query]

services/campaign_csv.py
└─ parse_campaign_csv()                        [Parse]

services/campaign_leads.py
├─ add_csv_rows()                              [Bulk add]
└─ add_lead_ids()                              [Link leads]
```

---

## 💡 Pro Tips

1. **Parallel vs Sequential**: Your tool code already uses `asyncio.gather()` for parallel execution. If Gemini calls 3 tools, they run simultaneously, not one after another. This is optimal ✓

2. **RTP Ports are Physical Limit**: 51 ports available (10000-10050). If you want 100+ concurrent calls, deploy multiple bridge instances.

3. **5-Call Ceiling**: The `max_concurrent_outbound=5` config is a *soft limit*, not a hard one. Database + Redis can handle 20+. Just increase the config and monitor pooling.

4. **Campaign Slot Filling**: Every 2 seconds, the campaign runner checks bridge for ended calls, then dials new leads. This rolling queue maintains constant load.

5. **Token Metering is Informational**: No hard token limit enforced. Metered per-call for pricing analytics. Configure rates in env vars (GEMINI_PRICE_AUDIO_INPUT_PER_1M, etc.)

6. **Call Window is Timezone-Aware**: Can respect different timezones per lead (set OUTBOUND_CALL_TIMEZONE in config).

7. **DNC List Blocks All Outbound**: Any phone on DNC → dial will raise PermissionError. Useful for compliance (TCPA, GDPR).

8. **Post-Call is Async**: Session close triggers summarization, lead capture, etc. asynchronously. Doesn't block call end.

9. **Session & CampaignLead Linkage**: Both inbound (Session) and outbound (CampaignLead linked to Session) get persisted. Analytics can trace lead through full lifecycle.

10. **Asterisk ARI Manages Bridges**: Your code doesn't create bridges directly. Asterisk does. Your bridge service just listens for stasisStart events and creates RTP ports + Gemini sessions.

---

## 📞 Common Questions Answered

**Q: Why can't I dial more than 5 calls?**
A: `max_concurrent_outbound = 5` in config.py. Change to 20, restart. RTP ports (51 available) are the real limit. Database connections scale easily at 5-20.

**Q: Do tool calls block the conversation?**
A: No! Parallel `asyncio.gather()` means if Gemini calls 3 tools simultaneously, they all run at once (typically <150ms total). Conversation flows smoothly.

**Q: Can a campaign spawn more calls than max_concurrent_outbound?**
A: No. Campaign runner respects both its own max_parallel AND the global max_concurrent_outbound. If global=5, even if campaign requests 10, only 5 will dial.

**Q: What happens if a call disconnects mid-tool?**
A: Tool execution completes (or times out), results sent to Gemini, but call is already hung up. Gemini session closes, post-call processing runs async.

**Q: How do I add a new tool?**
A: (1) Add declaration to TOOL_DECLARATIONS in tool_executor.py. (2) Add handler in tool_executor.dispatch(). (3) Add agent to enabled_tools list. (4) Restart platform.

**Q: Can I have both inbound and outbound simultaneously?**
A: Yes! They share the bridge but inbound is "unlimited" (51 RTP ports) while outbound is capped at max_concurrent_outbound. Example: 30 inbound + 5 outbound = 35 RTP ports used.

**Q: Where are tool call logs?**
A: Every tool call persisted in ToolCall table. Query: `SELECT * FROM tool_call WHERE session_id = 42 ORDER BY created_at`. Also in response.tool_call events.

**Q: How do I monitor what's happening?**
A: (1) Health endpoint: GET /api/health/concurrency. (2) Session queries: GET /api/sessions. (3) Campaign queries: GET /api/campaigns/{id}. (4) Logs: `docker logs aura_platform | grep "tool"`.

**Q: Why Gemini 3.1 Flash Live vs text-only?**
A: Voice is lower latency (real-time audio), better for natural conversation, native tool calling. Text requires transcription step + higher latency.

**Q: Can I use a different LLM?**
A: Backend uses Gemini APIs. To switch (e.g., OpenAI), would need substantial refactor (different APIs, different session management). Not currently supported.

---

## 📈 Metrics to Track

### Performance
- Average call duration
- Tool call latency (p50, p95, p99)
- Session success rate (completed vs error)
- Token usage per call

### Capacity
- Concurrent calls (active)
- DB connection pool utilization
- RTP port usage
- Campaign runner efficiency (leads/sec)

### Business
- Conversion rate (lead → qualified)
- Cost per call (tokens × pricing)
- Campaign completion time
- Lead quality (first contact → close)

---

## 🎓 Learning Path

1. **Beginner**: Read QUICK_REFERENCE.md (15 min)
2. **Intermediate**: Read CODEBASE_ANALYSIS.md (45 min)
3. **Advanced**: Read TECHNICAL_DEEP_DIVE.md (60 min)
4. **Expert**: Explore code files with references above (2-4 hours)

---

## ✅ Checklist: Key Takeaways

- [ ] Outbound was built by adding thin orchestration layer on inbound core (85% reuse)
- [ ] Tool calling is parallelized via `asyncio.gather()` for performance
- [ ] Max concurrent outbound = 5 (configurable, not hard limit)
- [ ] RTP ports (51) are physical limit for concurrent calls
- [ ] Campaign runner fills slots every 2 seconds as calls end
- [ ] All sessions (inbound + outbound) use same GeminiLiveSession + tool infrastructure
- [ ] Tool calls persisted to DB for audit trail
- [ ] Token usage metered per-call for pricing (no hard limit)
- [ ] Call window & DNC enforced for compliance
- [ ] Post-call processing (summarization, lead capture) is async non-blocking

---

**Generated**: June 2026 | **Comprehensive Analysis Complete**

📖 **Start Reading**:
1. First time? → CODEBASE_ANALYSIS.md
2. Need quick facts? → QUICK_REFERENCE.md
3. Implementing changes? → TECHNICAL_DEEP_DIVE.md
