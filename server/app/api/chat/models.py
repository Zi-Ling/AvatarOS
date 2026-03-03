# app/api/task.py
"""
API 数据模型（请求和响应）
"""
from pydantic import BaseModel, Field
from typing import Literal


# ============ Chat 相关 ============

class ChatMessage(BaseModel):
    """聊天消息"""
    role: Literal["user", "assistant", "system"]
    content: str


class ImageAttachment(BaseModel):
    """图片附件"""
    name: str = Field(..., description="文件名")
    data: str = Field(..., description="Base64 编码的图片数据")
    mime_type: str = Field(default="image/png", description="MIME 类型")


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(..., description="用户输入的消息")
    session_id: str | None = Field(None, description="会话ID，不传则创建新会话")
    stream: bool = Field(default=True, description="是否使用流式响应")
    enable_think: bool = Field(default=False, description="是否启用思考模式（CoT）")
    images: list[ImageAttachment] = Field(default_factory=list, description="图片附件列表")


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""
    message: str = Field(..., description="AI 回复的消息")
    task_id: str | None = Field(None, description="如果执行了任务，返回任务ID")


class StreamChunk(BaseModel):
    """流式响应片段"""
    content: str = Field("", description="文本内容片段")
    done: bool = Field(False, description="是否完成")
    task_id: str | None = Field(None, description="任务ID（完成时返回）")
    session_id: str | None = Field(None, description="会话ID")


# ============ Session 相关 ============

class SessionResponse(BaseModel):
    """会话响应"""
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: list[SessionResponse]
    total: int


class MessageResponse(BaseModel):
    """消息响应"""
    id: str
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str


class SessionHistoryResponse(BaseModel):
    """会话历史响应"""
    session_id: str
    messages: list[MessageResponse]


# ============ Task/Run/Step 相关 ============

class StepResponse(BaseModel):
    """步骤响应"""
    id: str
    step_index: int
    step_name: str
    skill_name: str
    status: str  # pending | running | completed | failed | skipped
    input_params: dict | None = None
    output_result: dict | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class RunResponse(BaseModel):
    """运行响应"""
    id: str
    task_id: str
    status: str  # pending | running | completed | failed | cancelled
    summary: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    steps: list[StepResponse] = []


class TaskDetailResponse(BaseModel):
    """任务详情响应"""
    id: str
    title: str
    intent_spec: dict
    task_mode: str  # one_shot | recurring
    created_at: str
    updated_at: str
    runs: list[RunResponse] = []


class TaskListItemResponse(BaseModel):
    """任务列表项响应"""
    id: str
    title: str
    task_mode: str
    created_at: str
    last_run_status: str | None = None
    run_count: int = 0


class TaskListResponse(BaseModel):
    """任务列表响应"""
    tasks: list[TaskListItemResponse]
    total: int


# ============ Speech 相关 ============

class TranscribeResponse(BaseModel):
    """语音识别响应"""
    text: str = Field(..., description="识别的文字")
    language: str = Field(..., description="检测到的语言")
    language_probability: float = Field(..., description="语言置信度")
    duration: float = Field(..., description="音频时长（秒）")


class SpeechModelInfoResponse(BaseModel):
    """语音模型信息"""
    loaded: bool = Field(..., description="模型是否已加载")
    model_path: str | None = Field(None, description="模型路径")
    device: str | None = Field(None, description="运行设备 (cpu/cuda)")
    compute_type: str | None = Field(None, description="计算类型")

