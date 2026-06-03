from celery import Celery
from backend.config import get_settings

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
