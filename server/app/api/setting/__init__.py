from .settings import router as settings_router
from .maintenance import router as maintenance_router
from .schedule import router as schedule_router

__all__ = ["settings_router", "maintenance_router", "schedule_router"]
