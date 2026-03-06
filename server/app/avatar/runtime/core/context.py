from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from enum import Enum
from datetime import datetime
import uuid
import time
import json

if TYPE_CHECKING:
    from app.avatar.memory.manager import MemoryManager
    # Try to import Task/StepResult for type hinting if available
    try:
        from app.avatar.planner.models import Task, StepResult, TaskStatus as PlannerTaskStatus
    except ImportError:
        Task = Any
        StepResult = Any
        PlannerTaskStatus = Any

# --- 1. Task Identity ---
@dataclass
class TaskIdentity:
    task_id: str
    session_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    initiator: str = "user"
    created_at: float = field(default_factory=time.time)

    @classmethod
    def new(cls, task_id: str = None, session_id: str = None, parent_id: str = None) -> "TaskIdentity":
        return cls(
            task_id=task_id or str(uuid.uuid4()),
            session_id=session_id,
            parent_task_id=parent_id
        )

# --- 2. Goal & Constraints ---
@dataclass
class TaskGoal:
    description: str
    structured_intent: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)

# --- 3. Status & Progress ---
class TaskState(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "SUCCESS" # Map to Planner TaskStatus.SUCCESS
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

@dataclass
class RepairAttempt:
    """单次修复尝试记录"""
    attempt_number: int
    timestamp: float
    patch_type: str  # "insert" | "replace"
    patch_data: Dict[str, Any]
    result: str  # "success" | "failed" | "validation_failed"
    error_after_repair: Optional[str] = None

@dataclass
class RepairState:
    """Repair Loop 状态机"""
    is_repairing: bool = False
    current_attempt: int = 0
    max_attempts: int = 3
    failed_step_id: Optional[str] = None
    original_code: Optional[str] = None
    original_error: Optional[str] = None
    repair_history: List[RepairAttempt] = field(default_factory=list)
    last_repair_at: Optional[float] = None
    
    def can_retry(self) -> bool:
        """是否还能尝试修复"""
        return self.current_attempt < self.max_attempts
    
    def add_attempt(self, attempt: RepairAttempt) -> None:
        """记录一次修复尝试"""
        self.repair_history.append(attempt)
        self.current_attempt = attempt.attempt_number
        self.last_repair_at = attempt.timestamp

@dataclass
class TaskStatusManager:
    state: TaskState = TaskState.PENDING
    current_step_index: int = 0
    total_steps: int = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    repair_state: RepairState = field(default_factory=RepairState)  # 新增：Repair 状态

    @property
    def progress(self) -> float:
        if self.total_steps == 0: return 0.0
        return min(1.0, self.current_step_index / self.total_steps)

# --- 4. Inputs & Variables ---
@dataclass
class TaskVariables:
    inputs: Dict[str, Any] = field(default_factory=dict)
    vars: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any):
        self.vars[key] = value

    def get(self, key: str, default=None) -> Any:
        return self.vars.get(key, default)

# --- 5. Artifacts ---
@dataclass
class Artifact:
    id: str
    type: str
    uri: str
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TaskArtifacts:
    items: List[Artifact] = field(default_factory=list)

    def add(self, type: str, uri: str, meta: dict = None) -> Artifact:
        art = Artifact(id=str(uuid.uuid4()), type=type, uri=uri, meta=meta or {})
        self.items.append(art)
        return art

# --- 6. History ---
@dataclass
class StepRecord:
    step_index: int
    skill_name: str
    status: str
    inputs: Dict[str, Any]
    outputs: Any
    duration_ms: float
    timestamp: float
    step_id: str = ""
    depends_on: List[str] = field(default_factory=list)  # 新增：步骤依赖
    description: str = ""  # 新增：步骤描述

@dataclass
class TaskHistory:
    steps: List[StepRecord] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def add_step(self, record: StepRecord):
        self.steps.append(record)

# ==========================================
#               The TaskContext
# ==========================================
@dataclass
class TaskContext:
    identity: TaskIdentity
    goal: TaskGoal
    status: TaskStatusManager
    variables: TaskVariables
    artifacts: TaskArtifacts
    history: TaskHistory
    
    # Runtime Attachments (Not serialized)
    _memory_manager: Optional['MemoryManager'] = field(default=None, repr=False)
    _env: Dict[str, Any] = field(default_factory=dict, repr=False)
    _attachments: Dict[str, Any] = field(default_factory=dict, repr=False)
    # Legacy support
    step_results: Dict[str, Any] = field(default_factory=dict) 

    @classmethod
    def create(cls, goal_desc: str, inputs: dict = None, session_id: str = None, memory_manager: Optional['MemoryManager'] = None, task_id: str = None, env: dict = None) -> "TaskContext":
        return cls(
            identity=TaskIdentity.new(task_id=task_id, session_id=session_id),
            goal=TaskGoal(description=goal_desc),
            status=TaskStatusManager(),
            variables=TaskVariables(inputs=inputs or {}),
            artifacts=TaskArtifacts(),
            history=TaskHistory(),
            _memory_manager=memory_manager,
            _env=env or {}
        )

    # --- Legacy Compatibility: ExecutionContext.from_task ---
    @classmethod
    def from_task(cls, task: Any, env: Optional[Dict[str, Any]] = None) -> "TaskContext":
        # ✅ 修复：从 task.metadata 中提取 session_id
        session_id = None
        if hasattr(task, "metadata") and isinstance(task.metadata, dict):
            session_id = task.metadata.get("session_id")
        
        ctx = cls.create(
            goal_desc=getattr(task, "goal", ""),
            task_id=getattr(task, "id", None),
            session_id=session_id,  # 传递 session_id
            env=env
        )
        if hasattr(task, "steps"):
             ctx.status.total_steps = len(task.steps)
        return ctx

    # --- Legacy Properties ---
    @property
    def task_id(self) -> str:
        return self.identity.task_id

    @property
    def env(self) -> Dict[str, Any]:
        return self._env

    @property
    def vars(self) -> Dict[str, Any]:
        return self.variables.vars

    # --- Legacy Methods ---
    def attach(self, name: str, obj: Any) -> None:
        if name == "memory_manager":
            self._memory_manager = obj
        self._attachments[name] = obj

    def get_attachment(self, name: str) -> Any:
        if name == "memory_manager":
            return self._memory_manager
        return self._attachments.get(name)

    def get(self, key: str, default: Any = None, namespace: str = "vars") -> Any:
        if namespace == "env": return self._env.get(key, default)
        if namespace == "vars": return self.variables.get(key, default)
        if namespace == "steps": return self.step_results.get(key, default) # Legacy
        return self.variables.get(key, default)

    def set(self, key: str, value: Any, namespace: str = "vars") -> None:
        if namespace == "vars":
            self.variables.set(key, value)
        elif namespace == "env":
            self._env[key] = value
        self.save_snapshot()

    def set_step_result(self, step_id: str, result: Any) -> None:
        # Legacy storage
        self.step_results[step_id] = result
        
        # Smart sync to new structure
        output_val = getattr(result, "output", result) if result else None
        self.variables.set(f"step_result:{step_id}", output_val)
        self.variables.set("last_output", output_val)
        self.variables.set("last_step_id", step_id)
        
        self.save_snapshot()

    def get_step_result(self, step_id: str) -> Any:
        return self.step_results.get(step_id)

    def get_last_step_result(self) -> Any:
        last_id = self.variables.get("last_step_id")
        if last_id:
            return self.step_results.get(last_id)
        return None

    def save_snapshot(self):
        if self._memory_manager:
            try:
                # Serialize (Simplified)
                # We avoid serializing memory_manager itself
                data = {
                    "identity": asdict(self.identity),
                    "goal": asdict(self.goal),
                    "status": asdict(self.status),
                    "variables": asdict(self.variables),
                    "artifacts": asdict(self.artifacts), 
                    "history": asdict(self.history)
                }
                # Call set_working_state on memory_manager
                self._memory_manager.set_working_state(f"task:{self.task_id}:context", data)
            except Exception as e:
                # Silently ignore if serialization fails (e.g. unpicklable objects)
                # In prod, use a better logger
                pass

    # Status helpers
    def mark_running(self):
        self.status.state = TaskState.RUNNING
        if not self.status.start_time:
            self.status.start_time = time.time()
        self.save_snapshot()

    def mark_finished(self, status: str):
        try:
            self.status.state = TaskState(status)
        except:
            self.status.state = TaskState.FAILED
        self.status.end_time = time.time()
        self.save_snapshot()

    # ========================================
    # Serialization Support (for ProcessExecutor)
    # ========================================
    
    def __getstate__(self):
        """
        自定义序列化：排除不可序列化的字段
        
        这使得 TaskContext 可以通过 multiprocessing 传递给 ProcessExecutor。
        """
        import pickle
        import logging
        logger = logging.getLogger(__name__)
        
        state = self.__dict__.copy()
        
        # 排除不可序列化的字段
        state.pop('_memory_manager', None)
        state.pop('_event_bus', None)
        
        # 特殊处理 _attachments：只保留可序列化的部分
        if '_attachments' in state:
            attachments = state['_attachments'].copy()
            attachments.pop('memory_manager', None)
            attachments.pop('event_bus', None)
            attachments.pop('session_context', None)
            state['_attachments'] = attachments
        
        # 递归转换函数：将任何对象转换为可序列化的形式
        def make_serializable(obj, depth=0):
            """递归转换对象为可序列化形式"""
            if depth > 10:  # 防止无限递归
                return str(obj)
            
            # 尝试直接序列化
            try:
                pickle.dumps(obj)
                return obj
            except:
                pass
            
            # 处理字典
            if isinstance(obj, dict):
                return {k: make_serializable(v, depth+1) for k, v in obj.items()}
            
            # 处理列表
            if isinstance(obj, (list, tuple)):
                return [make_serializable(item, depth+1) for item in obj]
            
            # 处理有 items() 方法的对象（如 Bindings）
            if hasattr(obj, 'items') and callable(obj.items):
                try:
                    return {k: make_serializable(v, depth+1) for k, v in obj.items()}
                except:
                    pass
            
            # 处理有 __dict__ 的对象
            if hasattr(obj, '__dict__'):
                try:
                    return {k: make_serializable(v, depth+1) for k, v in obj.__dict__.items()}
                except:
                    pass
            
            # 最后兜底：转换为字符串
            return str(obj)
        
        # 特殊处理 variables：递归转换所有不可序列化的对象
        if 'variables' in state and state['variables'] is not None:
            try:
                original_vars = state['variables']
                
                # 转换 inputs
                inputs_dict = {}
                if hasattr(original_vars, 'inputs'):
                    inputs_dict = make_serializable(original_vars.inputs)
                
                # 转换 vars
                vars_dict = {}
                if hasattr(original_vars, 'vars'):
                    vars_dict = make_serializable(original_vars.vars)
                
                # 创建新的 TaskVariables 对象
                state['variables'] = TaskVariables(
                    inputs=inputs_dict if isinstance(inputs_dict, dict) else {},
                    vars=vars_dict if isinstance(vars_dict, dict) else {}
                )
            except Exception as e:
                logger.warning(f"[TaskContext] Failed to serialize variables: {e}, creating empty TaskVariables")
                state['variables'] = TaskVariables(inputs={}, vars={})
        
        return state
    
    def __setstate__(self, state):
        """
        自定义反序列化：恢复对象状态
        """
        self.__dict__.update(state)
        
        # 恢复被排除的字段为 None
        if '_memory_manager' not in self.__dict__:
            self._memory_manager = None
        if '_attachments' not in self.__dict__:
            self._attachments = {}

# Backward Alias
ExecutionContext = TaskContext

# --- StepContext (Updated) ---
@dataclass
class StepContext:
    """
    Proxy for TaskContext, exposing step-specific view.
    """
    execution: TaskContext
    step_id: str
    step_order: int = 0
    skill_name: str = ""

    @property
    def task_id(self) -> str:
        return self.execution.task_id

    @property
    def env(self) -> Dict[str, Any]:
        return self.execution.env

    def get_var(self, key: str, default: Any = None) -> Any:
        return self.execution.variables.get(key, default)

    def set_var(self, key: str, value: Any) -> None:
        self.execution.variables.set(key, value)
        self.execution.save_snapshot()

    def get_step_result(self, step_id: str) -> Any:
        return self.execution.get_step_result(step_id)

    def get_last_step_result(self) -> Any:
        return self.execution.get_last_step_result()

    def set_output(self, result: Any) -> None:
        self.execution.set_step_result(self.step_id, result)
    
    def attach(self, name: str, obj: Any) -> None:
        self.execution.attach(name, obj)

    def get_attachment(self, name: str) -> Any:
        return self.execution.get_attachment(name)

    # --- New Features ---
    def add_artifact(self, type: str, uri: str, meta: dict = None):
        self.execution.artifacts.add(type, uri, meta)
        self.execution.save_snapshot()

    def remember_knowledge(self, key: str, value: Any):
        mm = self.execution.get_attachment("memory_manager")
        if mm:
            mm.set_knowledge(key, value)
