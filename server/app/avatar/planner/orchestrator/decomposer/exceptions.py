"""
任务分解异常定义
"""


class TaskDecompositionError(Exception):
    """任务分解失败的基类"""
    pass


class DecompositionTimeoutError(TaskDecompositionError):
    """任务分解超时"""
    
    def __init__(self, message: str = "任务分解超时", retry_attempted: bool = False):
        """
        Args:
            message: 错误消息
            retry_attempted: 是否已经尝试过重试
        """
        self.retry_attempted = retry_attempted
        super().__init__(message)


class DecompositionParseError(TaskDecompositionError):
    """任务分解结果解析失败"""
    pass

