import logging

from celery import Celery
from celery.signals import worker_process_init

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery(
    "aura",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.services.document_indexer"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@worker_process_init.connect
def _dispose_db_engine_after_fork(**_kwargs) -> None:
    """Drop inherited async DB pool so each worker task gets a fresh loop."""
    try:
        from backend.db.database import engine

        engine.sync_engine.dispose()
    except Exception:
        logger.exception("Failed to dispose DB engine on Celery worker init")
