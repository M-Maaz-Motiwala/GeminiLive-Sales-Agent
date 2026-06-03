"""Background post-call processing: summary and structured outputs."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.db.database import AsyncSessionLocal
from backend.db.models import Agent, AgentType, Output, OutputType, Session as DBSession
from backend.services.summarizer import generate_output, generate_summary
from backend.services.session_timeline import merge_message_turns

logger = logging.getLogger(__name__)


async def process_call_end(session_id: int) -> None:
    """Generate summary (and lead_capture for lead agents) after SIP call ends."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession)
            .options(selectinload(DBSession.messages), selectinload(DBSession.agent))
            .where(DBSession.id == session_id)
        )
        db_session = result.scalar_one_or_none()
        if db_session is None:
            return

        turns = merge_message_turns(db_session.messages)
        messages = [{"role": t["role"], "text": t["text"]} for t in turns]
        if not messages:
            logger.info("Session %d has no messages; skipping post-call processing", session_id)
            return

        if not db_session.summary:
            summary = await generate_summary(messages)
            if summary:
                db_session.summary = summary
                logger.info("Auto-summary generated for session %d", session_id)

        agent = db_session.agent
        if agent and agent.type == AgentType.lead_qualification:
            existing = await db.execute(
                select(Output).where(
                    Output.session_id == session_id,
                    Output.output_type == OutputType.lead_capture,
                )
            )
            if existing.scalar_one_or_none() is None:
                lead_data = await generate_output("lead_capture", messages)
                if lead_data and "error" not in lead_data:
                    db.add(
                        Output(
                            session_id=session_id,
                            output_type=OutputType.lead_capture,
                            content=lead_data,
                        )
                    )
                    logger.info("Lead capture output saved for session %d", session_id)

        await db.commit()
