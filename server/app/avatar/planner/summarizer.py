"""
Result Summarizer: 将技术化的执行结果转换为用户友好的自然语言

职责：
1. 识别技能输出类型（时间、文件、搜索等）
2. 提取关键信息
3. 生成简洁的自然语言总结
"""
from typing import Any, Dict, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ResultSummarizer:
    """将技能执行结果转换为自然语言总结"""
    
    @staticmethod
    def summarize(skill_name: str, raw_output: Any, llm_client: Optional[Any] = None) -> str:
        """
        生成执行结果的自然语言总结
        
        Args:
            skill_name: 技能名称（如 "time.now", "file.create"）
            raw_output: 原始输出数据
            llm_client: 可选的LLM客户端，用于复杂总结
        
        Returns:
            用户友好的自然语言总结
        """
        try:
            # 策略1: 基于规则的快速总结（覆盖常见技能）
            rule_based_summary = ResultSummarizer._rule_based_summary(skill_name, raw_output)
            if rule_based_summary:
                return rule_based_summary
            
            # 策略2: LLM驱动的总结（用于复杂输出）
            if llm_client:
                return ResultSummarizer._llm_based_summary(skill_name, raw_output, llm_client)
            
            # 策略3: 降级方案（简单格式化）
            return ResultSummarizer._fallback_summary(skill_name, raw_output)
            
        except Exception as e:
            logger.error(f"Failed to summarize result for {skill_name}: {e}")
            return "执行完成"
    
    @staticmethod
    def _rule_based_summary(skill_name: str, raw_output: Any) -> Optional[str]:
        """基于规则的快速总结"""
        
        if not isinstance(raw_output, dict):
            # 非字典输出，直接返回
            if isinstance(raw_output, str) and len(raw_output) < 100:
                return raw_output
            return None
        
        # === 时间类技能 ===
        if skill_name.startswith("time."):
            if "now_utc_iso" in raw_output:
                try:
                    dt = datetime.fromisoformat(raw_output["now_utc_iso"].replace("+00:00", ""))
                    # 转换为北京时间（UTC+8）
                    from datetime import timezone, timedelta
                    beijing_tz = timezone(timedelta(hours=8))
                    beijing_time = dt.replace(tzinfo=timezone.utc).astimezone(beijing_tz)
                    
                    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
                    weekday = weekdays[beijing_time.weekday()]
                    
                    return f"现在是 {beijing_time.strftime('%Y年%m月%d日 %H:%M')}，{weekday}"
                except Exception as e:
                    logger.warning(f"Failed to parse time: {e}")
                    return "已获取当前时间"
        
        # === 文件类技能 ===
        if skill_name.startswith("file."):
            # 创建文件
            if "path" in raw_output and skill_name in ["file.create", "file.write", "file.write_text"]:
                path = raw_output["path"]
                filename = path.split("/")[-1] if "/" in path else path.split("\\")[-1] if "\\" in path else path
                return f"已创建文件：{filename}"
            
            # 读取文件
            if "content" in raw_output and skill_name in ["file.read", "file.read_text"]:
                content = raw_output["content"]
                if isinstance(content, str):
                    length = len(content)
                    if length < 50:
                        return f"文件内容：{content}"
                    else:
                        return f"已读取文件（{length} 字符）"
            
            # 搜索文件
            if "files" in raw_output and skill_name == "file.search":
                files = raw_output["files"]
                if isinstance(files, list):
                    count = len(files)
                    if count == 0:
                        return "未找到匹配的文件"
                    elif count == 1:
                        return f"找到 1 个文件：{files[0]}"
                    else:
                        return f"找到 {count} 个文件"
            
            # 删除文件
            if skill_name == "file.delete":
                return "文件已删除"
        
        # === 日程类技能 ===
        if skill_name.startswith("schedule."):
            if "events" in raw_output:
                events = raw_output["events"]
                if isinstance(events, list):
                    count = len(events)
                    if count == 0:
                        return "今天没有日程安排"
                    else:
                        return f"找到 {count} 个日程安排"
        
        # === 搜索类技能 ===
        if "search" in skill_name.lower():
            if "results" in raw_output:
                results = raw_output["results"]
                if isinstance(results, list):
                    count = len(results)
                    return f"找到 {count} 个搜索结果"
        
        # 没有匹配的规则
        return None
    
    @staticmethod
    def _llm_based_summary(skill_name: str, raw_output: Any, llm_client: Any) -> str:
        """使用LLM生成总结（用于复杂输出）"""
        try:
            # 构建简单的总结prompt
            prompt = f"""请用一句简短的中文总结以下技能执行结果（不超过30字）：

技能：{skill_name}
输出：{str(raw_output)[:500]}

要求：
1. 只返回总结文本，不要额外解释
2. 使用用户友好的语言
3. 突出关键信息

总结："""
            
            # 调用LLM（统一接口）
            response = llm_client.call(prompt)
            
            # 清理响应
            summary = response.strip()
            if len(summary) > 100:
                summary = summary[:100] + "..."
            
            return summary
            
        except Exception as e:
            logger.warning(f"LLM-based summary failed: {e}")
            return ResultSummarizer._fallback_summary(skill_name, raw_output)
    
    @staticmethod
    def _fallback_summary(skill_name: str, raw_output: Any) -> str:
        """降级方案：简单格式化"""
        
        # 尝试提取有意义的字段
        if isinstance(raw_output, dict):
            # 优先显示常见的有意义字段
            meaningful_fields = ["message", "result", "data", "output", "summary"]
            for field in meaningful_fields:
                if field in raw_output and raw_output[field]:
                    value = raw_output[field]
                    if isinstance(value, str) and len(value) < 100:
                        return value
            
            # 如果有path字段，显示文件名
            if "path" in raw_output:
                return f"操作完成：{raw_output['path']}"
            
            # 统计非空字段数量
            non_null_fields = [k for k, v in raw_output.items() if v is not None]
            if len(non_null_fields) > 0:
                return f"执行完成（返回 {len(non_null_fields)} 个字段）"
        
        return "执行完成"
    
    @staticmethod
    def extract_progress_message(skill_name: str, status: str = "running") -> str:
        """
        生成技能执行的进度消息
        
        Args:
            skill_name: 技能名称
            status: 状态（running, completed, failed）
        
        Returns:
            进度消息
        """
        # 技能类别映射
        skill_actions = {
            "time.": "获取时间信息",
            "file.create": "创建文件",
            "file.write": "写入文件",
            "file.read": "读取文件",
            "file.search": "搜索文件",
            "file.delete": "删除文件",
            "schedule.": "处理日程",
            "search.": "执行搜索",
            "llm.": "调用AI模型",
        }
        
        # 查找匹配的动作
        action = "执行任务"
        for prefix, desc in skill_actions.items():
            if skill_name.startswith(prefix):
                action = desc
                break
        
        # 根据状态生成消息
        if status == "running":
            return f"正在{action}..."
        elif status == "completed":
            return f"{action}完成"
        elif status == "failed":
            return f"{action}失败"
        else:
            return action

