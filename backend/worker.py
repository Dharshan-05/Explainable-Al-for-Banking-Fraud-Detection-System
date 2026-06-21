# ============================================================
#  worker.py  —  Celery Application
#  Broker & backend: Redis
# ============================================================

from celery import Celery
from config import settings

celery_app = Celery(
    "fraud_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["tasks.predict_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Tasks expire after 1 hour
    result_expires=3600,
    # Retry failed tasks up to 3 times
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_max_retries=3,
    # Fix PendingDeprecationWarning in Celery 5.3+
    broker_connection_retry_on_startup=True,
)
