"""Legacy entry point — delegates to seed_agents.py (3 agents)."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backend.scripts.seed_agents import seed_agents  # noqa: E402


async def seed_agent():
    await seed_agents()


if __name__ == "__main__":
    asyncio.run(seed_agent())
