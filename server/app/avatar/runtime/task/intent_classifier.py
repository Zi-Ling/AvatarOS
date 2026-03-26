"""
IntentClassifier — lightweight rule-based intent classification.

Classifies user intent into task_kind categories and detects specific
intent signals (action verbs, desktop entities, time loops, etc.)
used by:
- Direct reply guard (Change 2): block FINISH for action intents
- VisionGate capability routing (Change 3): detect desktop automation needs
- Task type lock (Change 4): assign task_kind to TaskDefinition
- Continuous task routing (Change 7): detect scheduled/loop patterns
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, List, Optional, Pattern


class TaskKind(str, Enum):
    """Stable task kind classification — once assigned, downstream
    components (Planner, PlanBuilder) are forbidden from drifting."""
    DESKTOP_CONTROL = "desktop_control"       # 操作桌面应用/窗口/鼠标/键盘
    APP_USAGE = "app_usage"                   # 使用已有应用完成任务
    SOFTWARE_BUILD = "software_build"         # 编写/开发/构建软件
    INFORMATION_QUERY = "information_query"   # 查询/搜索/问答
    FILE_OPERATION = "file_operation"         # 文件读写/转换/整理
    DATA_ANALYSIS = "data_analysis"           # 数据分析/统计/可视化
    CONTINUOUS_LOOP = "continuous_loop"       # 持续型/定时循环任务
    GENERAL = "general"                       # 无法归类


@dataclass
class IntentSignals:
    """Detected intent signals from user request text."""
    has_action_verb: bool = False
    has_desktop_entity: bool = False
    has_time_loop: bool = False
    has_file_product: bool = False
    has_build_intent: bool = False
    has_query_intent: bool = False
    has_vision_dependency: bool = False  # needs screen reading/visual judgment
    task_kind: TaskKind = TaskKind.GENERAL
    matched_patterns: List[str] = field(default_factory=list)

    @property
    def requires_execution(self) -> bool:
        """True if intent clearly requires execution, not just a text reply."""
        return (
            self.has_action_verb
            or self.has_desktop_entity
            or self.has_time_loop
            or self.has_file_product
        )

    @property
    def requires_desktop_automation(self) -> bool:
        """True if intent needs desktop control skills."""
        return self.has_desktop_entity and self.has_action_verb


# ── Configurable pattern definitions ────────────────────────────────


@dataclass(frozen=True)
class IntentPatternConfig:
    """All intent classification patterns in one place.

    Centralises regex patterns that were previously scattered as module-level
    constants. Allows downstream users to override patterns (e.g. add custom
    app names, verbs, or entities) without modifying source code.

    Each field is a raw regex string. Compiled patterns are cached on first
    use via ``compiled()`` to avoid re-compilation overhead.
    """

    # Action verbs that require execution (not just explanation)
    action_verbs: str = (
        r'(?:打开|启动|运行|执行|点击|双击|右键|滑动|滚动|拖拽|拖动|'
        r'输入|键入|按下|松开|关闭|最小化|最大化|还原|切换|'
        r'安装|卸载|下载|上传|复制|粘贴|剪切|删除|移动|重命名|'
        r'创建|生成|写入|保存|导出|发送|提交|'
        r'open|launch|run|execute|click|double.click|right.click|'
        r'scroll|swipe|drag|drop|type|press|release|close|minimize|'
        r'maximize|restore|switch|install|uninstall|download|upload|'
        r'copy|paste|cut|delete|move|rename|create|generate|write|save|export|send|submit)'
    )

    # Desktop entities (apps, windows, UI elements)
    # NOTE: app names (抖音|微信|QQ|...) are intentionally included as
    # defaults. Override this field to add/remove app names for your env.
    desktop_entities: str = (
        r'(?:程序|应用|软件|窗口|桌面|任务栏|开始菜单|托盘|图标|'
        r'按钮|菜单|对话框|弹窗|标签页|选项卡|'
        r'浏览器|记事本|终端|命令行|资源管理器|文件管理器|'
        r'抖音|微信|QQ|钉钉|飞书|企业微信|'
        r'Chrome|Firefox|Edge|Safari|Notepad|Explorer|Terminal|'
        r'PowerShell|CMD|VSCode|Word|Excel|PowerPoint|Outlook|'
        r'app|application|window|desktop|taskbar|tray|icon|'
        r'button|menu|dialog|popup|tab)'
    )

    # Time/loop patterns indicating continuous/scheduled tasks
    time_loop: str = (
        r'(?:每[隔过]?\s*\d+\s*[秒分钟小时天]|'
        r'定时|循环|重复|持续|不断|一直|'
        r'every\s+\d+\s*(?:second|minute|hour|day)|'
        r'loop|repeat|continuously|periodically|schedule)'
    )

    # File product patterns
    file_product: str = (
        r'(?:保存[到为]|导出[到为]|生成.*文件|写入.*文件|输出.*文件|'
        r'save\s+(?:to|as)|export\s+(?:to|as)|generate.*file|write.*file|output.*file|'
        r'\.(?:txt|csv|json|xlsx|docx|pdf|png|jpg|html|md|py|js))'
    )

    # Software build intent
    build_intent: str = (
        r'(?:开发|编写|编程|写代码|实现|构建|搭建|部署|'
        r'develop|code|program|implement|build|deploy|architect)'
    )

    # Query/information intent
    query_intent: str = (
        r'(?:查询|搜索|查找|查看|列出|显示|告诉我|是什么|怎么样|'
        r'什么是|如何|为什么|解释|说明|介绍|'
        r'search|find|list|show|tell\s+me|what\s+is|how\s+to|why|explain|describe)'
    )

    # Vision-dependent patterns (need screen reading)
    vision_dependency: str = (
        r'(?:看[到见]|识别|检测|截图|屏幕上|画面|显示的|'
        r'看一下|观察|监控屏幕|'
        r'see|recognize|detect|screenshot|on\s+screen|display)'
    )

    def compiled(self) -> "_CompiledIntentPatterns":
        """Return compiled regex patterns (cached per config instance)."""
        # frozen dataclass → safe to cache on the class; but since frozen
        # we store on a module-level dict keyed by id.
        return _compile_patterns(self)


# ── Compiled pattern cache ──────────────────────────────────────────

class _CompiledIntentPatterns:
    """Pre-compiled regex patterns from IntentPatternConfig."""
    __slots__ = (
        "action_verbs", "desktop_entities", "time_loop",
        "file_product", "build_intent", "query_intent",
        "vision_dependency",
    )

    def __init__(self, cfg: IntentPatternConfig) -> None:
        self.action_verbs: Pattern = re.compile(cfg.action_verbs, re.IGNORECASE)
        self.desktop_entities: Pattern = re.compile(cfg.desktop_entities, re.IGNORECASE)
        self.time_loop: Pattern = re.compile(cfg.time_loop, re.IGNORECASE)
        self.file_product: Pattern = re.compile(cfg.file_product, re.IGNORECASE)
        self.build_intent: Pattern = re.compile(cfg.build_intent, re.IGNORECASE)
        self.query_intent: Pattern = re.compile(cfg.query_intent, re.IGNORECASE)
        self.vision_dependency: Pattern = re.compile(cfg.vision_dependency, re.IGNORECASE)


_PATTERN_CACHE: dict = {}


def _compile_patterns(cfg: IntentPatternConfig) -> _CompiledIntentPatterns:
    key = id(cfg)
    cached = _PATTERN_CACHE.get(key)
    if cached is not None:
        return cached
    compiled = _CompiledIntentPatterns(cfg)
    _PATTERN_CACHE[key] = compiled
    return compiled


# ── Default config (module-level singleton) ─────────────────────────

_DEFAULT_CONFIG = IntentPatternConfig()


# ── Public API ──────────────────────────────────────────────────────

def classify_intent(
    text: str,
    config: Optional[IntentPatternConfig] = None,
) -> IntentSignals:
    """Classify user intent from raw text.

    Args:
        text: Raw user input text.
        config: Optional custom pattern config. Uses module default if None.

    Returns IntentSignals with all detected patterns and a task_kind.
    """
    cfg = config or _DEFAULT_CONFIG
    p = cfg.compiled()
    signals = IntentSignals()

    if p.action_verbs.search(text):
        signals.has_action_verb = True
        signals.matched_patterns.append("action_verb")

    if p.desktop_entities.search(text):
        signals.has_desktop_entity = True
        signals.matched_patterns.append("desktop_entity")

    if p.time_loop.search(text):
        signals.has_time_loop = True
        signals.matched_patterns.append("time_loop")

    if p.file_product.search(text):
        signals.has_file_product = True
        signals.matched_patterns.append("file_product")

    if p.build_intent.search(text):
        signals.has_build_intent = True
        signals.matched_patterns.append("build_intent")

    if p.query_intent.search(text):
        signals.has_query_intent = True
        signals.matched_patterns.append("query_intent")

    if p.vision_dependency.search(text):
        signals.has_vision_dependency = True
        signals.matched_patterns.append("vision_dependency")

    # ── Derive task_kind ────────────────────────────────────────────
    if signals.has_time_loop and signals.has_desktop_entity:
        signals.task_kind = TaskKind.CONTINUOUS_LOOP
    elif signals.has_desktop_entity and signals.has_action_verb and not signals.has_build_intent:
        signals.task_kind = TaskKind.DESKTOP_CONTROL
    elif signals.has_desktop_entity and not signals.has_build_intent:
        signals.task_kind = TaskKind.APP_USAGE
    elif signals.has_build_intent:
        signals.task_kind = TaskKind.SOFTWARE_BUILD
    elif signals.has_query_intent and not signals.has_action_verb:
        signals.task_kind = TaskKind.INFORMATION_QUERY
    elif signals.has_file_product:
        signals.task_kind = TaskKind.FILE_OPERATION
    else:
        signals.task_kind = TaskKind.GENERAL

    return signals
