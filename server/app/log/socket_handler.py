import logging
import asyncio
import json
from datetime import datetime
from app.io.manager import SocketManager

class SocketLogHandler(logging.Handler):
    """
    A logging handler that streams logs to frontend via Socket.IO.
    """
    def __init__(self):
        super().__init__()
        self.socket_manager = SocketManager.get_instance()
        self.loop = None 

    def emit(self, record):
        try:
            # Filter out socket.io logs to avoid recursive loops
            if "socket.io" in record.name or "engineio" in record.name:
                return

            log_entry = self.format(record)
            
            # Construct structured payload
            payload = {
                "timestamp": datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                "level": record.levelname,
                "module": record.name,
                "message": record.getMessage()
            }

            # Send async (thread-safe)
            try:
                # 1. Always try to get the currently running loop in this thread
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # 2. If no running loop (e.g. called from thread pool), fallback to stored loop
                    loop = self.loop
                
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.socket_manager.emit("server_event", {
                            "type": "system.log",
                            "payload": payload
                        }),
                        loop
                    )
                else:
                    # This happens if the loop is closed or not set yet
                    pass
            except Exception:
                # Ignore errors during emit to prevent crashing the logger
                pass
                
        except Exception:
            self.handleError(record)

