"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth.router import router as auth_router
from backend.routers.agents import router as agents_router
from backend.routers.sessions import router as sessions_router
from backend.routers.leads import router as leads_router
from backend.routers.contacts import router as contacts_router
from backend.routers.notes import router as notes_router
from backend.routers.documents import router as documents_router
from backend.routers.outputs import router as outputs_router
from backend.routers.ws_browser import router as ws_router
from backend.routers.calls import router as calls_router
from backend.routers.outbound import router as outbound_router
from backend.routers.campaigns import router as campaigns_router
from backend.routers.dnc import router as dnc_router
from backend.routers.internal_bridge import router as internal_bridge_router
from backend.routers.system import router as system_router
from backend.db.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Aura Intelligence Platform...")
    await init_db()
    # SIP telephony (ARI + RTP + Gemini) is owned by gemini_bridge — not here.
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Aura Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(sessions_router)
app.include_router(leads_router)
app.include_router(contacts_router)
app.include_router(notes_router)
app.include_router(documents_router)
app.include_router(outputs_router)
app.include_router(ws_router)
app.include_router(calls_router)
app.include_router(outbound_router)
app.include_router(campaigns_router)
app.include_router(dnc_router)
app.include_router(internal_bridge_router)
app.include_router(system_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "aura-intelligence-platform"}
