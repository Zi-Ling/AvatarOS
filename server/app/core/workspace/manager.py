# app/workspace_manager.py
"""
工作目录管理器
负责工作目录的配置、切换、验证
"""
from pathlib import Path
import json
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# 配置文件位置（用户主目录）
CONFIG_DIR = Path.home() / ".intelliavatar"
CONFIG_FILE = CONFIG_DIR / "workspace_config.json"


class WorkspaceManager:
    """工作目录管理器"""
    
    def __init__(self, default_workspace: Path):
        self.default_workspace = default_workspace.resolve()
        self._current_workspace: Optional[Path] = None
        self._recent_paths: List[str] = []
        self._on_change_callbacks = []
        self._load_config()

    def add_change_listener(self, callback):
        """注册工作目录变更监听器"""
        self._on_change_callbacks.append(callback)

    def _notify_listeners(self, new_path: Path):
        """通知监听器"""
        for callback in self._on_change_callbacks:
            try:
                callback(new_path)
            except Exception as e:
                logger.error(f"Error in workspace change listener: {e}")

    def _load_config(self):
        """加载配置文件"""
        if not CONFIG_FILE.exists():
            logger.info("📁 首次启动，使用默认工作目录")
            self._current_workspace = self.default_workspace
            self._ensure_workspace_exists()
            return
        
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
                # 读取当前路径
                current_path = config.get('current_path')
                if current_path:
                    path = Path(current_path)
                    if path.exists() and path.is_dir():
                        self._current_workspace = path
                        logger.info(f"📁 加载工作目录: {path}")
                    else:
                        logger.warning(f"⚠️ 配置的工作目录不存在，使用默认目录")
                        self._current_workspace = self.default_workspace
                else:
                    self._current_workspace = self.default_workspace
                
                # 读取最近使用列表
                self._recent_paths = config.get('recent_paths', [])
                
        except Exception as e:
            logger.error(f"❌ 加载配置失败: {e}，使用默认目录")
            self._current_workspace = self.default_workspace
        
        self._ensure_workspace_exists()
    
    def _save_config(self):
        """保存配置文件"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            
            config = {
                'default_path': str(self.default_workspace),
                'current_path': str(self._current_workspace),
                'recent_paths': self._recent_paths[:5],  # 只保存最近5个
                'last_updated': datetime.now().isoformat()
            }
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ 配置已保存")
            
        except Exception as e:
            logger.error(f"❌ 保存配置失败: {e}")
    
    def _ensure_workspace_exists(self):
        """确保工作目录存在"""
        if self._current_workspace:
            self._current_workspace.mkdir(parents=True, exist_ok=True)
    
    def _add_to_recent(self, path: Path):
        """添加到最近使用列表"""
        path_str = str(path)
        
        # 移除已存在的（避免重复）
        if path_str in self._recent_paths:
            self._recent_paths.remove(path_str)
        
        # 添加到开头
        self._recent_paths.insert(0, path_str)
        
        # 限制最多5个
        self._recent_paths = self._recent_paths[:5]
    
    def get_workspace(self) -> Path:
        """获取当前工作目录"""
        return self._current_workspace
    
    def set_workspace(self, path: str) -> Path:
        """
        设置工作目录
        
        Args:
            path: 新的工作目录路径
            
        Returns:
            Path: 设置后的工作目录路径
            
        Raises:
            ValueError: 路径无效
        """
        new_path = Path(path).resolve()
        
        # 验证路径
        if not new_path.exists():
            # 尝试创建
            try:
                new_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"无法创建目录: {e}")
        
        if not new_path.is_dir():
            raise ValueError(f"路径不是有效的目录: {new_path}")
        
        # 检查权限
        test_file = new_path / ".test_write"
        try:
            test_file.write_text("test")
            test_file.unlink()
        except Exception as e:
            raise ValueError(f"目录没有写入权限: {e}")
        
        # 设置新路径
        self._current_workspace = new_path
        self._add_to_recent(new_path)
        self._save_config()
        
        self._notify_listeners(new_path)

        logger.info(f"✅ 工作目录已切换为: {new_path}")
        return new_path
    
    def get_recent_paths(self) -> List[dict]:
        """
        获取最近使用的路径列表
        
        Returns:
            List[dict]: 路径信息列表
        """
        result = []
        for path_str in self._recent_paths:
            path = Path(path_str)
            result.append({
                'path': path_str,
                'exists': path.exists(),
                'is_default': path == self.default_workspace,
                'name': path.name if path != self.default_workspace else 'workspace (默认)'
            })
        return result
    
    def reset_to_default(self) -> Path:
        """重置到默认工作目录"""
        return self.set_workspace(str(self.default_workspace))
    
    def validate_path(self, path: str) -> dict:
        """
        验证路径是否有效
        
        Returns:
            dict: 验证结果
        """
        try:
            p = Path(path).resolve()
            
            return {
                'valid': p.exists() and p.is_dir(),
                'exists': p.exists(),
                'is_dir': p.is_dir() if p.exists() else False,
                'writable': self._check_writable(p) if p.exists() else False,
                'path': str(p)
            }
        except Exception as e:
            return {
                'valid': False,
                'error': str(e)
            }
    
    def _check_writable(self, path: Path) -> bool:
        """检查目录是否可写"""
        test_file = path / ".test_write"
        try:
            test_file.write_text("test")
            test_file.unlink()
            return True
        except:
            return False


# 全局实例（在 main.py 中初始化）
workspace_manager: Optional[WorkspaceManager] = None


def init_workspace_manager(default_workspace: Path):
    """初始化工作目录管理器"""
    global workspace_manager
    workspace_manager = WorkspaceManager(default_workspace)
    return workspace_manager


def get_workspace_manager() -> WorkspaceManager:
    """获取工作目录管理器实例"""
    if workspace_manager is None:
        raise RuntimeError("WorkspaceManager 未初始化")
    return workspace_manager


def get_current_workspace() -> Path:
    """
    获取当前 workspace 路径 — 全局唯一入口。

    所有需要 user workspace 路径的地方统一调此函数，
    不再散落 workspace_manager.get_workspace() / self.base_path 等多种写法。

    fallback 顺序：
      1. WorkspaceManager（已初始化）→ 动态取当前值，切换立即生效
      2. config.avatar_workspace → 启动配置默认值
    """
    try:
        return get_workspace_manager().get_workspace()
    except RuntimeError:
        from app.core.config import config
        return config.avatar_workspace.resolve()

