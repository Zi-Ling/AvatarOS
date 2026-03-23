# app/services/browser/__init__.py
"""Browser Automation Executor — L2 浏览器自动化子执行器。"""

from .models import (
    # Enums
    ActionPrimitiveType,
    BrowserErrorCode,
    ActionabilityFailureReason,
    SelectorType,
    SecurityLevel,
    BrowserVerificationStrategy,
    WaitUntilStrategy,
    FailurePolicy,
    PlaybackFailurePolicy,
    DialogAction,
    WaitForState,
    # Constants
    BROWSER_ERROR_DEGRADABLE,
    BROWSER_ERROR_DESCRIPTIONS,
    SELECTOR_PRIORITY,
    # Core models
    SelectorCandidate,
    SelectorResolution,
    VerificationSpec,
    ActionPrimitive,
    ActionabilityCheckDetail,
    ActionabilityResult,
    InteractiveElementSummary,
    FormFieldSummary,
    DialogInfo,
    PageStateSnapshot,
    BrowserVerificationResult,
    ActionResult,
    ExecutionResult,
    # Session models
    ResourceQuota,
    SessionHandle,
    BrowserContextHandle,
    PageHandle,
    ContextOptions,
    ContextSummary,
    PageSummary,
    # Failure / Recording / Config
    FailureContext,
    RecordingEntry,
    RecordingMetadata,
    Recording,
    PlaybackResult,
    BrowserAutomationConfig,
    ActionPolicyConfig,
)

from .errors import (
    BrowserAutomationError,
    SessionCapacityError,
    SessionNotFoundError,
    ForbiddenActionError,
    map_playwright_error,
    normalize_error,
    build_failure_context,
)
from .config import load_browser_config
from .session_manager import SessionManager
from .selector_strategy import SelectorStrategy
from .actionability import ActionabilityPipeline
from .verification_engine import VerificationEngine
from .action_policy import ActionPolicy
from .page_snapshot import capture_snapshot, truncate_snapshot
from .action_dispatcher import ActionDispatcher
from .recording import RecordingEngine, PlaybackEngine
from .executor import BrowserAutomationStepExecutor

__all__ = [
    # Enums
    "ActionPrimitiveType",
    "BrowserErrorCode",
    "ActionabilityFailureReason",
    "SelectorType",
    "SecurityLevel",
    "BrowserVerificationStrategy",
    "WaitUntilStrategy",
    "FailurePolicy",
    "PlaybackFailurePolicy",
    "DialogAction",
    "WaitForState",
    # Constants
    "BROWSER_ERROR_DEGRADABLE",
    "BROWSER_ERROR_DESCRIPTIONS",
    "SELECTOR_PRIORITY",
    # Core models
    "SelectorCandidate",
    "SelectorResolution",
    "VerificationSpec",
    "ActionPrimitive",
    "ActionabilityCheckDetail",
    "ActionabilityResult",
    "InteractiveElementSummary",
    "FormFieldSummary",
    "DialogInfo",
    "PageStateSnapshot",
    "BrowserVerificationResult",
    "ActionResult",
    "ExecutionResult",
    # Session models
    "ResourceQuota",
    "SessionHandle",
    "BrowserContextHandle",
    "PageHandle",
    "ContextOptions",
    "ContextSummary",
    "PageSummary",
    # Failure / Recording / Config
    "FailureContext",
    "RecordingEntry",
    "RecordingMetadata",
    "Recording",
    "PlaybackResult",
    "BrowserAutomationConfig",
    "ActionPolicyConfig",
    # Errors
    "BrowserAutomationError",
    "SessionCapacityError",
    "SessionNotFoundError",
    "ForbiddenActionError",
    "map_playwright_error",
    "normalize_error",
    "build_failure_context",
    # Config
    "load_browser_config",
    # Services
    "SessionManager",
    "SelectorStrategy",
    "ActionabilityPipeline",
    "VerificationEngine",
    "ActionPolicy",
    "capture_snapshot",
    "truncate_snapshot",
    "ActionDispatcher",
    "RecordingEngine",
    "PlaybackEngine",
    "BrowserAutomationStepExecutor",
]
