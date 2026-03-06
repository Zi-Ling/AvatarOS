"""
执行器监控指标

提供 Prometheus 格式的监控指标导出。
"""

import time
from typing import Dict, Optional
from collections import defaultdict
from threading import Lock


class ExecutorMetrics:
    """
    执行器监控指标收集器
    
    收集以下指标：
    - 执行次数（按执行器、Skill、状态）
    - 执行时间（启动时间、执行时间）
    - 错误率
    - 降级次数
    """
    
    def __init__(self):
        self._lock = Lock()
        
        # 执行计数器
        self._execution_count = defaultdict(lambda: defaultdict(int))
        # {executor_name: {skill_name: count}}
        
        # 成功/失败计数
        self._success_count = defaultdict(int)  # {executor_name: count}
        self._failure_count = defaultdict(int)  # {executor_name: count}
        
        # 执行时间（秒）
        self._execution_times = defaultdict(list)  # {executor_name: [time1, time2, ...]}
        
        # 降级计数
        self._fallback_count = defaultdict(int)  # {from_executor: count}
        
        # 当前活跃执行
        self._active_executions = defaultdict(int)  # {executor_name: count}
    
    def record_execution_start(self, executor_name: str, skill_name: str):
        """记录执行开始"""
        with self._lock:
            self._execution_count[executor_name][skill_name] += 1
            self._active_executions[executor_name] += 1
    
    def record_execution_end(
        self,
        executor_name: str,
        skill_name: str,
        duration: float,
        success: bool
    ):
        """记录执行结束"""
        with self._lock:
            self._active_executions[executor_name] -= 1
            self._execution_times[executor_name].append(duration)
            
            if success:
                self._success_count[executor_name] += 1
            else:
                self._failure_count[executor_name] += 1
    
    def record_fallback(self, from_executor: str, to_executor: str):
        """记录降级"""
        with self._lock:
            self._fallback_count[from_executor] += 1
    
    def get_prometheus_metrics(self) -> str:
        """
        导出 Prometheus 格式的指标
        
        Returns:
            Prometheus 文本格式的指标
        """
        with self._lock:
            lines = []
            
            # 1. 执行次数
            lines.append("# HELP executor_executions_total Total number of executions")
            lines.append("# TYPE executor_executions_total counter")
            for executor_name, skills in self._execution_count.items():
                for skill_name, count in skills.items():
                    lines.append(
                        f'executor_executions_total{{executor="{executor_name}",skill="{skill_name}"}} {count}'
                    )
            
            # 2. 成功次数
            lines.append("# HELP executor_executions_success_total Total number of successful executions")
            lines.append("# TYPE executor_executions_success_total counter")
            for executor_name, count in self._success_count.items():
                lines.append(f'executor_executions_success_total{{executor="{executor_name}"}} {count}')
            
            # 3. 失败次数
            lines.append("# HELP executor_executions_failure_total Total number of failed executions")
            lines.append("# TYPE executor_executions_failure_total counter")
            for executor_name, count in self._failure_count.items():
                lines.append(f'executor_executions_failure_total{{executor="{executor_name}"}} {count}')
            
            # 4. 错误率
            lines.append("# HELP executor_error_rate Error rate (0-1)")
            lines.append("# TYPE executor_error_rate gauge")
            for executor_name in self._success_count.keys():
                total = self._success_count[executor_name] + self._failure_count[executor_name]
                if total > 0:
                    error_rate = self._failure_count[executor_name] / total
                    lines.append(f'executor_error_rate{{executor="{executor_name}"}} {error_rate:.4f}')
            
            # 5. 执行时间（平均）
            lines.append("# HELP executor_execution_duration_seconds Average execution duration")
            lines.append("# TYPE executor_execution_duration_seconds gauge")
            for executor_name, times in self._execution_times.items():
                if times:
                    avg_time = sum(times) / len(times)
                    lines.append(f'executor_execution_duration_seconds{{executor="{executor_name}"}} {avg_time:.6f}')
            
            # 6. 执行时间（P50）
            lines.append("# HELP executor_execution_duration_p50_seconds P50 execution duration")
            lines.append("# TYPE executor_execution_duration_p50_seconds gauge")
            for executor_name, times in self._execution_times.items():
                if times:
                    sorted_times = sorted(times)
                    p50 = sorted_times[len(sorted_times) // 2]
                    lines.append(f'executor_execution_duration_p50_seconds{{executor="{executor_name}"}} {p50:.6f}')
            
            # 7. 执行时间（P95）
            lines.append("# HELP executor_execution_duration_p95_seconds P95 execution duration")
            lines.append("# TYPE executor_execution_duration_p95_seconds gauge")
            for executor_name, times in self._execution_times.items():
                if times:
                    sorted_times = sorted(times)
                    p95 = sorted_times[int(len(sorted_times) * 0.95)]
                    lines.append(f'executor_execution_duration_p95_seconds{{executor="{executor_name}"}} {p95:.6f}')
            
            # 8. 降级次数
            lines.append("# HELP executor_fallback_total Total number of fallbacks")
            lines.append("# TYPE executor_fallback_total counter")
            for from_executor, count in self._fallback_count.items():
                lines.append(f'executor_fallback_total{{from_executor="{from_executor}"}} {count}')
            
            # 9. 当前活跃执行
            lines.append("# HELP executor_active_executions Current number of active executions")
            lines.append("# TYPE executor_active_executions gauge")
            for executor_name, count in self._active_executions.items():
                lines.append(f'executor_active_executions{{executor="{executor_name}"}} {count}')
            
            return "\n".join(lines) + "\n"
    
    def get_summary(self) -> Dict:
        """
        获取指标摘要（用于日志或 API）
        
        Returns:
            指标摘要字典
        """
        with self._lock:
            summary = {}
            
            for executor_name in self._execution_count.keys():
                total_executions = sum(self._execution_count[executor_name].values())
                success = self._success_count.get(executor_name, 0)
                failure = self._failure_count.get(executor_name, 0)
                times = self._execution_times.get(executor_name, [])
                
                summary[executor_name] = {
                    "total_executions": total_executions,
                    "success_count": success,
                    "failure_count": failure,
                    "error_rate": failure / (success + failure) if (success + failure) > 0 else 0,
                    "avg_duration_ms": (sum(times) / len(times) * 1000) if times else 0,
                    "active_executions": self._active_executions.get(executor_name, 0),
                    "fallback_count": self._fallback_count.get(executor_name, 0),
                }
            
            return summary
    
    def reset(self):
        """重置所有指标（用于测试）"""
        with self._lock:
            self._execution_count.clear()
            self._success_count.clear()
            self._failure_count.clear()
            self._execution_times.clear()
            self._fallback_count.clear()
            self._active_executions.clear()


# 全局指标收集器
global_metrics = ExecutorMetrics()


def get_metrics() -> ExecutorMetrics:
    """获取全局指标收集器"""
    return global_metrics
