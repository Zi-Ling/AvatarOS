import logging
import os
from pathlib import Path
from typing import Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
import time
from app.avatar.runtime.events.types import EventType, Event

logger = logging.getLogger(__name__)

class AvatarFileSystemEventHandler(FileSystemEventHandler):
    """处理文件系统事件并转换为内部 Event"""
    
    def __init__(self, event_callback: Callable[[str, dict], None], base_path: Path):
        self.event_callback = event_callback
        self.base_path = base_path
        self._last_event_time = {}
        self._debounce_seconds = 0.5

    def _emit(self, event_type: str, src_path: str, is_directory: bool):
        # 忽略临时文件和隐藏文件
        filename = os.path.basename(src_path)
        
        # 常见的临时文件模式（Office、编辑器等）
        if any([
            filename.startswith('.'),           # 隐藏文件（如 .DS_Store）
            filename.startswith('~'),           # 通用临时文件（如 ~$file.docx）
            filename.startswith('~$'),          # Office 临时文件
            filename.startswith('~WRL'),        # Word 临时文件
            filename.endswith('.tmp'),          # 通用临时文件
            filename.endswith('.temp'),         # 通用临时文件
            filename.endswith('~'),             # 编辑器备份文件（如 file.txt~）
            filename.endswith('-journal'),      # SQLite 日志文件（如 avatar.db-journal）
            filename.endswith('-wal'),          # SQLite WAL 文件
            filename.endswith('-shm'),          # SQLite 共享内存文件
            filename.startswith('.~lock.'),     # LibreOffice 锁文件
            '__pycache__' in src_path,          # Python 缓存目录
            '.git' in src_path.split(os.sep),   # Git 目录
            'node_modules' in src_path.split(os.sep),  # Node 依赖目录
        ]):
            logger.debug(f"[Watcher] 🚫 Ignored temp/hidden file: {filename}")
            return

        # 计算相对路径
        try:
            rel_path = Path(src_path).relative_to(self.base_path)
            # 统一使用正斜杠
            rel_path_str = str(rel_path).replace(os.sep, '/')
        except ValueError:
            return # 不在监控目录下

        # 防抖处理（仅对 modified 事件防抖，created/deleted 必须立即处理）
        now = time.time()
        if event_type == 'modified':
            key = f"{event_type}:{rel_path_str}"
            if key in self._last_event_time:
                if now - self._last_event_time[key] < self._debounce_seconds:
                    logger.debug(f"[Watcher] 🔇 Debounced: {key}")
                    return
            self._last_event_time[key] = now

        # 映射到内部 EventType
        internal_type = None
        if event_type == 'created':
            internal_type = EventType.DIR_CREATED if is_directory else EventType.FILE_CREATED
        elif event_type == 'deleted':
            internal_type = EventType.DIR_DELETED if is_directory else EventType.FILE_DELETED
        elif event_type == 'modified':
            if not is_directory: # 通常只关心文件内容的修改
                internal_type = EventType.FILE_MODIFIED
        
        if internal_type:
            payload = {
                "path": rel_path_str,
                "type": "dir" if is_directory else "file",
                "fs_type": "dir" if is_directory else "file", # 兼容旧字段
                "timestamp": now
            }
            # 调用回调发送事件（日志已禁用，需要调试时取消注释）
            # logger.debug(f"[Watcher] {internal_type}: {rel_path_str}")
            self.event_callback(internal_type, payload)

    def on_created(self, event: FileSystemEvent):
        self._emit('created', event.src_path, event.is_directory)

    def on_deleted(self, event: FileSystemEvent):
        self._emit('deleted', event.src_path, event.is_directory)

    def on_modified(self, event: FileSystemEvent):
        self._emit('modified', event.src_path, event.is_directory)
    
    def on_moved(self, event: FileSystemEvent):
        # 移动 = 删除旧的 + 创建新的
        self._emit('deleted', event.src_path, event.is_directory)
        self._emit('created', event.dest_path, event.is_directory)


class FileSystemWatcher:
    """文件系统监控服务"""
    
    def __init__(self, event_bus_callback: Callable[[str, dict], None]):
        self.observer: Optional[Observer] = None
        self.event_callback = event_bus_callback
        self.current_path: Optional[Path] = None
        self._handler: Optional[AvatarFileSystemEventHandler] = None

    def start(self, path: Path):
        """开始监控指定目录"""
        logger.info(f"[FileSystemWatcher] Attempting to start monitoring: {path}")
        
        if self.observer:
            logger.info("[FileSystemWatcher] Stopping existing observer...")
            self.stop()

        if not path.exists():
            logger.warning(f"[FileSystemWatcher] Cannot watch non-existent path: {path}")
            return

        try:
            self.current_path = path
            self._handler = AvatarFileSystemEventHandler(self.event_callback, path)
            
            self.observer = Observer()
            self.observer.schedule(self._handler, str(path), recursive=True)
            self.observer.start()
            
            logger.info(f"[FileSystemWatcher] Started watching directory: {path}")
        except Exception as e:
            logger.error(f"[FileSystemWatcher] Failed to start: {e}")
            raise

    def stop(self):
        """停止监控"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            logger.info("👀 Stopped file system watcher")

    def update_path(self, new_path: Path):
        """切换监控目录"""
        if self.current_path != new_path:
            logger.info(f"🔄 Switching watch directory from {self.current_path} to {new_path}")
            self.start(new_path)

