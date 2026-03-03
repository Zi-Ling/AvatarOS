"""
Workflow Models

Data classes for workflow execution.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class WorkflowRunStatus(str, Enum):
    """工作流运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageRunStatus(str, Enum):
    """阶段运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageRun:
    """阶段执行记录"""
    stage_id: str
    stage_name: str
    status: StageRunStatus = StageRunStatus.PENDING
    
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    
    task_id: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    
    def mark_running(self) -> None:
        self.status = StageRunStatus.RUNNING
        self.start_time = time.time()
    
    def mark_success(self, outputs: Dict[str, Any] = None) -> None:
        self.status = StageRunStatus.SUCCESS
        self.end_time = time.time()
        if outputs:
            self.outputs.update(outputs)
    
    def mark_failed(self, error: str) -> None:
        self.status = StageRunStatus.FAILED
        self.end_time = time.time()
        self.error = error
    
    def mark_skipped(self) -> None:
        self.status = StageRunStatus.SKIPPED
        self.end_time = time.time()
    
    @property
    def duration(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


@dataclass
class WorkflowRun:
    """工作流执行记录"""
    id: str
    workflow_id: str
    workflow_name: str
    status: WorkflowRunStatus = WorkflowRunStatus.PENDING
    
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    stage_runs: List[StageRun] = field(default_factory=list)
    
    inputs: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    
    error: Optional[str] = None
    retry_count: int = 0
    
    def get_stage_run(self, stage_id: str) -> Optional[StageRun]:
        for sr in self.stage_runs:
            if sr.stage_id == stage_id:
                return sr
        return None
    
    def add_stage_run(self, stage_run: StageRun) -> None:
        self.stage_runs.append(stage_run)
    
    @property
    def duration(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "stage_runs": [
                {
                    "stage_id": sr.stage_id,
                    "stage_name": sr.stage_name,
                    "status": sr.status.value,
                    "duration": sr.duration,
                    "error": sr.error,
                    "retry_count": sr.retry_count
                }
                for sr in self.stage_runs
            ],
            "error": self.error,
            "retry_count": self.retry_count
        }

