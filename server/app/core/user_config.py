# server/app/core/user_config.py
"""
用户配置加载器
从 ~/.avatar/config.yaml 加载用户自定义配置
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

logger = logging.getLogger(__name__)

# 默认配置路径
DEFAULT_CONFIG_PATH = Path.home() / ".avatar" / "config.yaml"


class UserConfig:
    """用户配置管理器"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        if not self.config_path.exists():
            logger.info(f"User config not found at {self.config_path}, using defaults")
            self._config = self._get_default_config()
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
            logger.info(f"User config loaded from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load user config: {e}")
            self._config = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "fs": {
                "allowed_paths": [
                    str(Path.home() / "Documents"),
                    str(Path.home() / "Desktop"),
                    str(Path.home() / "Projects"),
                    str(Path.home() / "Downloads"),
                ],
                "forbidden_paths": [
                    str(Path.home() / ".ssh"),
                    str(Path.home() / ".aws"),
                    str(Path.home() / ".config"),
                    "/etc", "/sys", "/proc",
                ],
                "max_file_size_mb": 20,
                "default_encoding": "utf-8",
            },
            "net": {
                "allowed_domains": [
                    "*.github.com",
                    "*.githubusercontent.com",
                    "api.openai.com",
                    "*.deepseek.com",
                    "*.google.com",
                    "*.stackoverflow.com",
                ],
                "forbidden_domains": [
                    "localhost", "127.0.0.1",
                    "192.168.*", "10.*", "172.16.*",
                ],
                "timeout": 30,
                "max_redirects": 5,
            },
            "python": {
                "timeout": 30,
                "max_memory_mb": 512,
                "allowed_builtins": [
                    "print", "len", "range", "enumerate", "zip",
                    "map", "filter", "sorted", "sum", "min", "max",
                    "abs", "round",
                ],
                "allowed_modules": [
                    "math", "datetime", "json", "re",
                    "collections", "itertools",
                ],
            },
            "approval": {
                "auto_approve_low_risk": True,
                "low_risk_operations": [
                    "read_file", "list_directory", "search_web",
                ],
                "timeout": 60,
                "enabled": True,
            },
            "state": {
                "default_ttl": 3600,
                "cleanup_interval": 300,
            },
            "memory": {
                "vector_db": "chromadb",
                "default_limit": 5,
                "similarity_threshold": 0.7,
            },
            "audit": {
                "enabled": True,
                "retention_days": 30,
                "cleanup_interval": 86400,
            },
            "plan_compressor": {
                "enabled": True,
                "repeat_threshold": 3,
                "auto_rewrite": False,
            },
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持点号分隔的嵌套键）
        
        Examples:
            config.get("fs.max_file_size_mb")
            config.get("net.allowed_domains")
        """
        keys = key.split(".")
        value = self._config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            
            if value is None:
                return default
        
        return value
    
    def get_fs_config(self) -> Dict[str, Any]:
        """获取文件系统配置"""
        return self._config.get("fs", {})
    
    def get_net_config(self) -> Dict[str, Any]:
        """获取网络配置"""
        return self._config.get("net", {})
    
    def get_python_config(self) -> Dict[str, Any]:
        """获取 Python 沙箱配置"""
        return self._config.get("python", {})
    
    def get_approval_config(self) -> Dict[str, Any]:
        """获取审批配置"""
        return self._config.get("approval", {})
    
    def get_state_config(self) -> Dict[str, Any]:
        """获取状态管理配置"""
        return self._config.get("state", {})
    
    def get_memory_config(self) -> Dict[str, Any]:
        """获取记忆管理配置"""
        return self._config.get("memory", {})
    
    def get_audit_config(self) -> Dict[str, Any]:
        """获取审计日志配置"""
        return self._config.get("audit", {})
    
    def get_plan_compressor_config(self) -> Dict[str, Any]:
        """获取计划压缩器配置"""
        return self._config.get("plan_compressor", {})
    
    def is_path_allowed(self, path: str) -> bool:
        """检查路径是否允许访问"""
        from fnmatch import fnmatch
        
        path = str(Path(path).resolve())
        fs_config = self.get_fs_config()
        
        # 检查禁止路径
        forbidden = fs_config.get("forbidden_paths", [])
        for pattern in forbidden:
            if fnmatch(path, pattern) or path.startswith(pattern):
                return False
        
        # 检查允许路径
        allowed = fs_config.get("allowed_paths", [])
        if not allowed:
            return True  # 如果没有配置允许路径，默认允许
        
        for pattern in allowed:
            if fnmatch(path, pattern) or path.startswith(pattern):
                return True
        
        return False
    
    def is_domain_allowed(self, domain: str) -> bool:
        """检查域名是否允许访问"""
        from fnmatch import fnmatch
        
        net_config = self.get_net_config()
        
        # 检查禁止域名
        forbidden = net_config.get("forbidden_domains", [])
        for pattern in forbidden:
            if fnmatch(domain, pattern):
                return False
        
        # 检查允许域名
        allowed = net_config.get("allowed_domains", [])
        if not allowed:
            return True  # 如果没有配置允许域名，默认允许
        
        for pattern in allowed:
            if fnmatch(domain, pattern):
                return True
        
        return False
    
    def should_auto_approve(self, operation: str) -> bool:
        """检查操作是否应该自动批准"""
        approval_config = self.get_approval_config()
        
        if not approval_config.get("enabled", True):
            return True  # 如果审批功能未启用，自动批准所有操作
        
        if not approval_config.get("auto_approve_low_risk", True):
            return False  # 如果未启用自动批准低风险操作
        
        low_risk_ops = approval_config.get("low_risk_operations", [])
        return operation in low_risk_ops
    
    def reload(self):
        """重新加载配置文件"""
        self._load_config()
        logger.info("User config reloaded")


# 全局单例
_user_config: Optional[UserConfig] = None


def get_user_config() -> UserConfig:
    """获取全局 UserConfig 实例"""
    global _user_config
    if _user_config is None:
        _user_config = UserConfig()
    return _user_config
