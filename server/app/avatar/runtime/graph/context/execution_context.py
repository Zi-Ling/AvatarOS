"""
ExecutionContext: Unified Runtime Data Management

This module provides a centralized context for managing all runtime data during graph execution,
including node outputs, artifacts, session memory, environment variables, secrets, and user variables.

ExecutionContext extends TaskContext to maintain backward compatibility while adding graph-specific
functionality with thread-safe operations for concurrent node execution.

Requirements: 29.1-29.13
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from threading import Lock
import logging
from cryptography.fernet import Fernet
import base64
import os

from app.avatar.runtime.core.context import TaskContext

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.step_node import NodeStatus

logger = logging.getLogger(__name__)


class ExecutionContext(TaskContext):
    """
    Unified runtime context for graph execution.
    
    Extends TaskContext with graph-specific features:
    - Thread-safe node output management
    - Artifact tracking with metadata
    - Encrypted secrets storage
    - Session memory for cross-node data sharing
    - Node-level locking for distributed execution support
    
    Requirements:
    - 29.1: Contains graph_id, node_outputs, artifacts, session_memory, environment, secrets, variables
    - 29.2: Stores node_outputs as Dict[node_id, outputs]
    - 29.3: Stores artifacts as Dict[artifact_id, Artifact]
    - 29.4: Stores session_memory for cross-node shared data
    - 29.5: Stores environment variables
    - 29.6: Stores secrets with encryption
    - 29.7: Stores user-defined runtime variables
    - 29.13: Provides thread-safe access methods
    """
    
    def __init__(
        self,
        graph_id: str,
        goal_desc: str = "",
        inputs: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        memory_manager: Optional[Any] = None,
        task_id: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        encryption_key: Optional[bytes] = None
    ):
        """
        Initialize ExecutionContext.
        
        Args:
            graph_id: Unique identifier for the execution graph
            goal_desc: High-level goal description
            inputs: Initial input parameters
            session_id: Session identifier for tracking
            memory_manager: Optional memory manager for persistence
            task_id: Optional task identifier (defaults to graph_id)
            env: Environment variables
            encryption_key: Optional encryption key for secrets (generates one if not provided)
        """
        # Initialize parent TaskContext
        super().__init__(
            identity=TaskContext.create(
                goal_desc=goal_desc,
                inputs=inputs,
                session_id=session_id,
                memory_manager=memory_manager,
                task_id=task_id or graph_id,
                env=env
            ).identity,
            goal=TaskContext.create(goal_desc=goal_desc).goal,
            status=TaskContext.create(goal_desc=goal_desc).status,
            variables=TaskContext.create(goal_desc=goal_desc, inputs=inputs).variables,
            artifacts=TaskContext.create(goal_desc=goal_desc).artifacts,
            history=TaskContext.create(goal_desc=goal_desc).history,
            _memory_manager=memory_manager,
            _env=env or {}
        )
        
        # Graph-specific fields (Requirement 29.1)
        self.graph_id = graph_id
        
        # Node outputs storage (Requirement 29.2)
        self._node_outputs: Dict[str, Dict[str, Any]] = {}
        
        # Artifact metadata storage (Requirement 29.3)
        # Note: Actual artifact data is stored in ArtifactStore
        self._artifact_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Session memory for cross-node data sharing (Requirement 29.4)
        self._session_memory: Dict[str, Any] = {}
        
        # Environment variables (Requirement 29.5)
        # Already handled by parent TaskContext._env
        
        # Encrypted secrets storage (Requirement 29.6)
        self._secrets: Dict[str, str] = {}  # Stores encrypted values
        self._encryption_key = encryption_key or Fernet.generate_key()
        self._cipher = Fernet(self._encryption_key)
        
        # User-defined runtime variables (Requirement 29.7)
        # Already handled by parent TaskContext.variables
        
        # Thread-safe locks (Requirement 29.13)
        self._node_outputs_lock = Lock()
        self._artifacts_lock = Lock()
        self._session_memory_lock = Lock()
        self._secrets_lock = Lock()
        
        # Node-level locks for distributed execution support
        self._node_locks: Dict[str, Lock] = {}
        self._node_locks_lock = Lock()
    
    # ==========================================
    # Node Output Management (Thread-Safe)
    # ==========================================
    
    def set_node_output(self, node_id: str, outputs: Dict[str, Any]) -> None:
        """
        Store node execution outputs in a thread-safe manner.
        
        Args:
            node_id: Unique node identifier
            outputs: Dictionary of output values
            
        Requirements: 29.2, 29.9, 29.13
        """
        with self._node_outputs_lock:
            self._node_outputs[node_id] = outputs
            logger.debug(f"[ExecutionContext] Stored outputs for node {node_id}")
    
    def get_node_output(self, node_id: str, field: Optional[str] = None) -> Optional[Any]:
        """
        Retrieve node execution outputs in a thread-safe manner.
        
        Args:
            node_id: Unique node identifier
            field: Optional specific field to retrieve
            
        Returns:
            Node outputs dictionary or specific field value, None if not found
            
        Requirements: 29.2, 29.10, 29.13
        """
        with self._node_outputs_lock:
            outputs = self._node_outputs.get(node_id)
            if outputs is None:
                return None
            if field is None:
                return outputs
            return outputs.get(field)
    
    def get_all_node_outputs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all node outputs (thread-safe copy).
        
        Returns:
            Dictionary mapping node_id to outputs
            
        Requirements: 29.2, 29.13
        """
        with self._node_outputs_lock:
            return self._node_outputs.copy()
    
    def get_node_outputs_by_status(self, status: 'NodeStatus') -> Dict[str, Dict[str, Any]]:
        """
        Query node outputs filtered by node status.
        
        Note: This requires access to the ExecutionGraph to check node status.
        This is a placeholder implementation that returns all outputs.
        The actual filtering should be done by the caller with graph access.
        
        Args:
            status: Node status to filter by
            
        Returns:
            Dictionary of node outputs matching the status
            
        Requirements: 29.14
        """
        # This is a simplified implementation
        # In practice, the caller should filter based on graph.nodes[node_id].status
        with self._node_outputs_lock:
            return self._node_outputs.copy()
    
    # ==========================================
    # Artifact Management (Thread-Safe)
    # ==========================================
    
    def set_artifact(
        self,
        artifact_id: str,
        artifact_type: str,
        uri: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Store artifact metadata in a thread-safe manner.
        
        Note: Actual artifact data should be stored in ArtifactStore.
        This only stores metadata for tracking.
        
        Args:
            artifact_id: Unique artifact identifier
            artifact_type: Type of artifact (file, dataset, image, etc.)
            uri: URI/path to the artifact
            metadata: Optional additional metadata
            
        Requirements: 29.3, 29.13
        """
        with self._artifacts_lock:
            self._artifact_metadata[artifact_id] = {
                "id": artifact_id,
                "type": artifact_type,
                "uri": uri,
                "metadata": metadata or {}
            }
            logger.debug(f"[ExecutionContext] Stored artifact metadata for {artifact_id}")
    
    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve artifact metadata in a thread-safe manner.
        
        Args:
            artifact_id: Unique artifact identifier
            
        Returns:
            Artifact metadata dictionary or None if not found
            
        Requirements: 29.3, 29.13
        """
        with self._artifacts_lock:
            return self._artifact_metadata.get(artifact_id)
    
    def get_artifacts_by_type(self, artifact_type: str) -> List[Dict[str, Any]]:
        """
        Query artifacts filtered by type.
        
        Args:
            artifact_type: Type of artifact to filter by
            
        Returns:
            List of artifact metadata dictionaries matching the type
            
        Requirements: 29.14
        """
        with self._artifacts_lock:
            return [
                artifact for artifact in self._artifact_metadata.values()
                if artifact.get("type") == artifact_type
            ]
    
    def get_all_artifacts(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all artifact metadata (thread-safe copy).
        
        Returns:
            Dictionary mapping artifact_id to metadata
            
        Requirements: 29.3, 29.13
        """
        with self._artifacts_lock:
            return self._artifact_metadata.copy()
    
    # ==========================================
    # Session Memory Management (Thread-Safe)
    # ==========================================
    
    def set_session_memory(self, key: str, value: Any) -> None:
        """
        Store data in session memory for cross-node sharing.
        
        Args:
            key: Memory key
            value: Value to store
            
        Requirements: 29.4, 29.13
        """
        with self._session_memory_lock:
            self._session_memory[key] = value
            logger.debug(f"[ExecutionContext] Stored session memory: {key}")
    
    def get_session_memory(self, key: str, default: Any = None) -> Any:
        """
        Retrieve data from session memory.
        
        Args:
            key: Memory key
            default: Default value if key not found
            
        Returns:
            Stored value or default
            
        Requirements: 29.4, 29.13
        """
        with self._session_memory_lock:
            return self._session_memory.get(key, default)
    
    def get_all_session_memory(self) -> Dict[str, Any]:
        """
        Get all session memory (thread-safe copy).
        
        Returns:
            Dictionary of all session memory
            
        Requirements: 29.4, 29.13
        """
        with self._session_memory_lock:
            return self._session_memory.copy()
    
    # ==========================================
    # Secrets Management (Encrypted, Thread-Safe)
    # ==========================================
    
    def set_secret(self, key: str, value: str) -> None:
        """
        Store a secret with encryption.
        
        Args:
            key: Secret key
            value: Secret value (will be encrypted)
            
        Requirements: 29.6, 29.13
        """
        with self._secrets_lock:
            encrypted_value = self._cipher.encrypt(value.encode()).decode()
            self._secrets[key] = encrypted_value
            logger.debug(f"[ExecutionContext] Stored encrypted secret: {key}")
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Retrieve and decrypt a secret.
        
        Args:
            key: Secret key
            default: Default value if key not found
            
        Returns:
            Decrypted secret value or default
            
        Requirements: 29.6, 29.13
        """
        with self._secrets_lock:
            encrypted_value = self._secrets.get(key)
            if encrypted_value is None:
                return default
            try:
                return self._cipher.decrypt(encrypted_value.encode()).decode()
            except Exception as e:
                logger.error(f"[ExecutionContext] Failed to decrypt secret {key}: {e}")
                return default
    
    def has_secret(self, key: str) -> bool:
        """
        Check if a secret exists.
        
        Args:
            key: Secret key
            
        Returns:
            True if secret exists, False otherwise
            
        Requirements: 29.6, 29.13
        """
        with self._secrets_lock:
            return key in self._secrets
    
    # ==========================================
    # Node-Level Locking (Distributed Execution Support)
    # ==========================================
    
    def acquire_node_lock(self, node_id: str, blocking: bool = True, timeout: float = -1) -> bool:
        """
        Acquire a lock for a specific node.
        
        This supports future distributed execution where multiple workers
        might try to execute the same node.
        
        Args:
            node_id: Node identifier
            blocking: Whether to block waiting for the lock
            timeout: Timeout in seconds (-1 for infinite)
            
        Returns:
            True if lock acquired, False otherwise
            
        Requirements: 29.1 (locks field), 29.13
        """
        with self._node_locks_lock:
            if node_id not in self._node_locks:
                self._node_locks[node_id] = Lock()
            lock = self._node_locks[node_id]
        
        return lock.acquire(blocking=blocking, timeout=timeout if timeout >= 0 else None)
    
    def release_node_lock(self, node_id: str) -> None:
        """
        Release a node lock.
        
        Args:
            node_id: Node identifier
            
        Requirements: 29.1 (locks field), 29.13
        """
        with self._node_locks_lock:
            if node_id in self._node_locks:
                self._node_locks[node_id].release()
    
    # ==========================================
    # Serialization Support
    # ==========================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize ExecutionContext to dictionary for persistence.
        
        Returns:
            Dictionary representation of the context
            
        Requirements: 29.11
        """
        # Get parent TaskContext serialization
        base_dict = {
            "identity": self.identity.__dict__,
            "goal": self.goal.__dict__,
            "status": self.status.__dict__,
            "variables": {
                "inputs": self.variables.inputs,
                "vars": self.variables.vars
            },
            "artifacts": [art.__dict__ for art in self.artifacts.items],
            "history": {
                "steps": [step.__dict__ for step in self.history.steps],
                "logs": self.history.logs
            }
        }
        
        # Add graph-specific fields
        with self._node_outputs_lock, self._artifacts_lock, self._session_memory_lock, self._secrets_lock:
            base_dict.update({
                "graph_id": self.graph_id,
                "node_outputs": self._node_outputs.copy(),
                "artifact_metadata": self._artifact_metadata.copy(),
                "session_memory": self._session_memory.copy(),
                "secrets": self._secrets.copy(),  # Already encrypted
                "encryption_key": base64.b64encode(self._encryption_key).decode()
            })
        
        return base_dict
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExecutionContext':
        """
        Deserialize ExecutionContext from dictionary.
        
        Args:
            data: Dictionary representation
            
        Returns:
            Restored ExecutionContext instance
            
        Requirements: 29.12
        """
        # Extract encryption key
        encryption_key = base64.b64decode(data.get("encryption_key", ""))
        
        # Create new instance
        ctx = cls(
            graph_id=data["graph_id"],
            goal_desc=data["goal"]["description"],
            inputs=data["variables"]["inputs"],
            session_id=data["identity"].get("session_id"),
            task_id=data["identity"]["task_id"],
            env=data.get("env", {}),
            encryption_key=encryption_key
        )
        
        # Restore graph-specific state
        ctx._node_outputs = data.get("node_outputs", {})
        ctx._artifact_metadata = data.get("artifact_metadata", {})
        ctx._session_memory = data.get("session_memory", {})
        ctx._secrets = data.get("secrets", {})
        
        # Restore parent state
        ctx.status.state = data["status"]["state"]
        ctx.status.current_step_index = data["status"]["current_step_index"]
        ctx.status.total_steps = data["status"]["total_steps"]
        ctx.status.start_time = data["status"].get("start_time")
        ctx.status.end_time = data["status"].get("end_time")
        
        return ctx
    
    # ==========================================
    # Backward Compatibility
    # ==========================================
    
    @classmethod
    def from_task_context(cls, task_context: TaskContext, graph_id: str) -> 'ExecutionContext':
        """
        Create ExecutionContext from existing TaskContext.
        
        This provides backward compatibility with existing code.
        
        Args:
            task_context: Existing TaskContext instance
            graph_id: Graph identifier
            
        Returns:
            New ExecutionContext instance with copied state
        """
        ctx = cls(
            graph_id=graph_id,
            goal_desc=task_context.goal.description,
            inputs=task_context.variables.inputs,
            session_id=task_context.identity.session_id,
            memory_manager=task_context._memory_manager,
            task_id=task_context.task_id,
            env=task_context._env
        )
        
        # Copy state
        ctx.status = task_context.status
        ctx.variables = task_context.variables
        ctx.artifacts = task_context.artifacts
        ctx.history = task_context.history
        ctx.step_results = task_context.step_results
        
        return ctx
