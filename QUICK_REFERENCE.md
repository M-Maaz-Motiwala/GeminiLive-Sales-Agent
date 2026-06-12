# Quick Reference: Tool Calling & Concurrency

## Tool Calling Flow (Visual)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GEMINI 3.1 FLASH LIVE API                        │
│                   (Automatic Tool Recognition)                      │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                   [Gemini decides to call tool]
                             │
                    ┌────────▼────────┐
                    │  Tool Call      │
                    │  {              │
                    │    name:        │
                    │    "create_     │
                    │     lead",      │
                    │    id: "tc_1",  │
                    │    args: {...}  │
                    │  }              │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ response.       │
                    │ tool_call       │
                    │ event detected  │
                    └────────┬────────┘
                             │
      ┌──────────────────────┴──────────────────────┐
      │                                             │
      │    GeminiLiveSession._handle_tool_call()   │
      │    ├─ Extract FunctionCalls[]              │
      │    └─ For each FunctionCall:               │
      │       └─ run_one(fc) async                 │
      │                                             │
      └──────────────────────┬──────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
    Tool 1: create_lead  Tool 2: search_kb  Tool 3: create_note
    [Parallel Execution via asyncio.gather()]
         │                   │                   │
         │ 80ms              │ 120ms             │ 60ms
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │ All complete (max 120ms)
         ┌───────────────────▼───────────────────┐
         │  Return FunctionResponse[] to Gemini  │
         │  {                                    │
         │    name: "create_lead",               │
         │    response: {"lead_id": 456}         │
         │  }                                    │
         │  {                                    │
         │    name: "search_kb",                 │
         │    response: {"docs": [...]}          │
         │  }                                    │
         │  {                                    │
         │    name: "create_note",               │
         │    response: {"note_id": 789}         │
         │  }                                    │
         └───────────────────┬───────────────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │  Gemini Receives Results              │
         │  (In-context, decides next action)    │
         └───────────────────┬───────────────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │  Gemini Generates Audio Response      │
         │  "Great! I found 3 matching leads..." │
         └───────────────────┬───────────────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │  Audio Output via RTP to Caller       │
         └─────────────────────────────────────────┘
```

---

## Tool Execution Timeline (Parallel vs Sequential)

### PARALLEL (Your Implementation - Optimal)
```
Tool Call Request: [create_lead, search_kb, create_note]
                    │
                    ├─ create_lead()       ══════════════════ 80ms
                    ├─ search_kb()         ════════════════════════ 120ms
                    └─ create_note()       ════════════ 60ms
                    │
                    └──────────────────────────────────── Total: 120ms (max of 3)

Gemini gets results after 120ms, responds with all 3 tool outcomes.
```

### SEQUENTIAL (What NOT to do)
```
Tool Call Request: [create_lead, search_kb, create_note]
                    │
                    ├─ create_lead()       ══════════════════ 80ms
                    │
                    ├─ search_kb()         ════════════════════════ 120ms
                    │
                    └─ create_note()       ════════════ 60ms
                    │
                    └──────────────────────────────────── Total: 260ms (sum)

Gemini waits 260ms for all results. Conversational latency suffers.
```

**Your code uses PARALLEL → Better UX ✓**

---

## Concurrency Limits Explained

### Global Constraint: 5 Concurrent Outbound Calls

```python
# In config.py
max_concurrent_outbound: int = 5

# Why 5?
# - Bridge capacity: 51 RTP ports available (10000-10050)
# - Database: Default pool ~20 connections
# - Redis: Single queue
# - Conservative starting point for cost control
```

### Example: Campaign with 5 Slots

```
TIME: 0s
┌─ Campaign "Tech Leads" (max_parallel=5)
│  ├─ Lead 1: PJSIP/1001      [DIALING]
│  ├─ Lead 2: PJSIP/1002      [DIALING]
│  ├─ Lead 3: PJSIP/1003      [DIALING]
│  ├─ Lead 4: PJSIP/1004      [DIALING]
│  ├─ Lead 5: PJSIP/1005      [DIALING]
│  ├─ Lead 6:                 [PENDING] ← queued
│  └─ Lead 7:                 [PENDING] ← queued
└─ active_dials = 5 (slots full)

TIME: 15s (Lead 1 ends)
┌─ Campaign "Tech Leads"
│  ├─ Lead 1:                 [COMPLETED] ✓
│  ├─ Lead 2: PJSIP/1002      [DIALING]
│  ├─ Lead 3: PJSIP/1003      [DIALING]
│  ├─ Lead 4: PJSIP/1004      [DIALING]
│  ├─ Lead 5: PJSIP/1005      [DIALING]
│  ├─ Lead 6: PJSIP/1001      [DIALING] ← auto-filled
│  └─ Lead 7:                 [PENDING]
└─ active_dials = 5 (slot refilled)

TIME: 20s (Lead 2 ends)
┌─ Campaign "Tech Leads"
│  ├─ Lead 1:                 [COMPLETED]
│  ├─ Lead 2:                 [COMPLETED] ✓
│  ├─ Lead 3: PJSIP/1003      [DIALING]
│  ├─ Lead 4: PJSIP/1004      [DIALING]
│  ├─ Lead 5: PJSIP/1005      [DIALING]
│  ├─ Lead 6: PJSIP/1001      [DIALING]
│  └─ Lead 7: PJSIP/1002      [DIALING] ← auto-filled
└─ active_dials = 5 (slot refilled)
```

### Campaign Runner Loop (Every 2 Seconds)

```python
POLL_SEC = 2.0

async def _run_loop(campaign_id, max_parallel):
    while is_runner_active(campaign_id):
        # Step 1: Reconcile with bridge
        bridge = await bridge_status()
        bridge_channels = {ch["channel_id"] for ch in bridge["calls"]}
        
        # Step 2: Mark completed leads
        # (Remove from active_dials if channel not in bridge_channels)
        active_dials = await _reconcile_active(db, campaign, active_dials, bridge_channels)
        
        # Step 3: Calculate free slots
        free_slots = max_parallel - len(active_dials)
        
        # Step 4: Fill free slots
        if free_slots > 0:
            active_dials = await _fill_slots(db, campaign, agent, active_dials, free_slots)
        
        # Step 5: Sleep 2 seconds, repeat
        await asyncio.sleep(2.0)
```

**Key Insight**: Slots fill as fast as calls end, maintaining constant load.

---

## Call Window & DNC (Outbound Only)

```python
# In config.py
outbound_call_window_enabled: bool = True
outbound_call_timezone: str = "UTC"
outbound_call_hour_start: int = 9
outbound_call_hour_end: int = 18

# In outbound_policy.py
def within_call_window():
    """Check if current time is within allowed window."""
    if not settings.outbound_call_window_enabled:
        return True, "disabled"
    
    tz = pytz.timezone(settings.outbound_call_timezone)
    now = datetime.now(tz)
    hour = now.hour
    
    if hour < settings.outbound_call_hour_start:
        return False, f"Too early (before {settings.outbound_call_hour_start}:00)"
    if hour >= settings.outbound_call_hour_end:
        return False, f"Too late (after {settings.outbound_call_hour_end}:00)"
    
    return True, "within window"

# Usage before dial
await assert_may_dial(db, phone=phone)  # Checks DNC list + call window
```

---

## Agent Type Matrix

```python
class AgentType(str, enum.Enum):
    sales              # Inbound: Aura Tech product sales
    research           # Inbound: Research assistant
    code_analysis      # Inbound: Code review agent
    document_qa        # Inbound: Document Q&A
    lead_qualification # Inbound: BANT questions
    outbound_sales     # OUTBOUND: Cold call dialer
    summarization      # Inbound: Summary generation
    router             # (Reserved for multi-agent routing)
```

**Key Difference**:
- **Inbound agents**: Can be any type (sales, research, etc.)
- **Outbound agents**: Must be `outbound_sales`
- **Enforcement**: `dial_one()` validates `agent.type == AgentType.outbound_sales`

---

## Session & Campaign Lead Status Lifecycle

### Inbound Session (SIP)
```
Creation: Session(status=ACTIVE)
    ↓ (Caller talks, tools called)
    ↓
Completion: await session.close()
    ├─ status = ENDED
    ├─ token_usage populated
    ├─ Post-call processing async
    └─ Unregistered from session_manager
```

### Outbound Campaign Lead
```
Creation: CampaignLead(status=PENDING)
    ↓ (Campaign runner fills slot)
    ├─ dial_one() → originate via bridge
    ├─ status = DIALING
    ├─ dialed_at = now
    └─ recorded channel_id
    ↓ (Gemini converses with lead)
    ├─ Session created
    ├─ Tools called (create_lead, etc.)
    ├─ Call ends
    └─ Session.close() async
    ↓ (Campaign runner reconciles)
    ├─ Detects channel gone from bridge
    ├─ CampaignLead.status = COMPLETED
    ├─ CampaignLead.session_id = linked session
    └─ Lead.source_session_id = session_id
```

---

## Database Relationships

```
Agent (1)
    ├─ (n) Session       [inbound: sip/web, outbound: outbound]
    │   ├─ (n) Message   [user/model turns]
    │   ├─ (n) ToolCall  [tool invocations + results]
    │   ├─ (n) Output    [summary, lead_capture, action_items]
    │   ├─ (1) Lead      [source_session_id → if lead created]
    │   └─ (1) Note      [entity_type=session, entity_id=session.id]
    │
    └─ (n) Campaign      [outbound only]
        ├─ (n) CampaignLead
        │   ├─ (1) Lead         [nullable]
        │   ├─ (1) Session      [attached after channel enters bridge]
        │   └─ meta: {"channel_id", "started_at"}
        └─ meta: {"runner": {"active_dials": {...}}}
```

---

## Why 85% Code Reuse? (Architecture Elegance)

### Shared Components (No Changes)
- ✓ GeminiLiveSession class
- ✓ Tool declarations & dispatcher
- ✓ RTP bridge & audio processing
- ✓ Message/ToolCall persistence
- ✓ Session manager registry
- ✓ Post-call summarization
- ✓ Token metering

### New Components (Outbound Only)
- ✗ Campaign model
- ✗ CampaignLead model
- ✗ Campaign runner loop
- ✗ Endpoint resolver
- ✗ Outbound policy (call window)
- ✗ Campaign CSV parser

### Modified Components (Minimal)
- ~ Session model: Added `channel_type` enum (inbound: sip/web, outbound: outbound)
- ~ Agent model: Added `AgentType.outbound_sales`
- ~ Agent config: Enabled tools per agent (was already there)
- ~ Post-call: Check for campaign_lead_id in session.meta (else null)

**Result**: ~200 lines of new code, ~2000 lines of core code reused → 85% reuse ✓

---

## Next: Scaling to 20+ Concurrent Calls

### Quick Wins (No Architecture Changes)
1. Increase `max_concurrent_outbound` to 20
2. Add PostgreSQL connection pooling (PgBouncer)
3. Monitor bridge RTP port usage (51 limit)
4. Add health check alerts

### Medium-Term (Minimal Changes)
1. Deploy 2nd bridge instance
2. Add load balancer to bridge_client (round-robin)
3. Implement campaign persistence (CampaignRun table)
4. Add basic campaign retry logic

### Long-Term (Architectural)
1. Multi-region Asterisk cluster
2. Advanced analytics dashboard
3. Agent Optimizer integration
4. Call recording infrastructure

---

## Debugging Checklist

### If Campaign Not Dialing
- [ ] Check `campaign.status` = "running"
- [ ] Check `bridge_status()` → is bridge healthy?
- [ ] Check `campaign.meta["runner"]` → runner active?
- [ ] Check `max_concurrent_outbound` → already at limit?
- [ ] Check `outbound_policy` → within call window?
- [ ] Check DNC list → are leads on DNC?
- [ ] Check agent.type → is it `outbound_sales`?

### If Tool Not Executing
- [ ] Check `agent.enabled_tools` → tool in list?
- [ ] Check tool declaration → JSON schema valid?
- [ ] Check `tool_executor.dispatch()` → function exists?
- [ ] Check database → can write Lead/Note records?
- [ ] Check logs → any exceptions in dispatch?

### If Audio Not Flowing
- [ ] Check RTP ports → range 10000-10050 open?
- [ ] Check Asterisk ARI → is it healthy?
- [ ] Check bridge WebSocket → Gemini session alive?
- [ ] Check PCM conversion → ulaw↔PCM16 working?
- [ ] Check token_usage → audio bytes accumulating?

---

**Quick Ref Version** | **Last Updated**: June 2026 | **For**: Complete Analysis, see CODEBASE_ANALYSIS.md
