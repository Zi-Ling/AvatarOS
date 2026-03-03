"""
Task Complexity Analyzer

Analyzes task complexity based on NLP metrics.
Inspired by Microsoft Semantic Kernel.
"""
import re
from typing import Tuple


class ComplexityAnalyzer:
    """
    任务复杂度分析器
    
    基于 NLP 指标量化分析任务复杂度：
    - 动词数量（动作越多越复杂）
    - 句子/步骤数量
    - 连接词数量（表示多步骤）
    - 文件类型多样性
    """
    
    # 动作动词列表
    ACTION_VERBS = [
        '创建', '写入', '读取', '提取', '生成', '打开', '关闭', '删除',
        '复制', '移动', '搜索', '查找', '替换', '修改', '添加', '保存',
        'create', 'write', 'read', 'extract', 'generate', 'open', 'close',
        'delete', 'copy', 'move', 'search', 'find', 'replace', 'modify', 'add'
    ]
    
    # 连接词列表
    CONNECTORS = [
        '然后', '接着', '再', '之后', '最后',
        'then', 'next', 'after', 'finally', 'and then'
    ]
    
    # 文件类型列表
    FILE_TYPES = [
        'txt', 'excel', 'word', 'pdf', 'json', 'csv', 'xml', 'html',
        'docx', 'xlsx', 'pptx'
    ]
    
    @staticmethod
    def analyze(goal_text: str, raw_input: str = "") -> float:
        """
        分析任务复杂度
        
        Args:
            goal_text: 目标描述
            raw_input: 原始用户输入
            
        Returns:
            复杂度得分 (0.0 - 1.0)
            0.0 = 最简单
            1.0 = 最复杂
        """
        combined_text = f"{goal_text} {raw_input}".lower()
        
        # 1. 动词数量得分
        verb_score = ComplexityAnalyzer._calculate_verb_score(combined_text)
        
        # 2. 句子数量得分
        sentence_score = ComplexityAnalyzer._calculate_sentence_score(combined_text)
        
        # 3. 连接词得分
        connector_score = ComplexityAnalyzer._calculate_connector_score(combined_text)
        
        # 4. 文件类型多样性得分
        type_score = ComplexityAnalyzer._calculate_type_score(combined_text)
        
        # 加权平均（动词和步骤权重更高）
        complexity = (
            0.35 * verb_score +
            0.30 * sentence_score +
            0.20 * connector_score +
            0.15 * type_score
        )
        
        return complexity
    
    @staticmethod
    def analyze_with_breakdown(goal_text: str, raw_input: str = "") -> Tuple[float, dict]:
        """
        分析任务复杂度并返回详细分解
        
        Returns:
            (总分, 详细分解字典)
        """
        combined_text = f"{goal_text} {raw_input}".lower()
        
        verb_score = ComplexityAnalyzer._calculate_verb_score(combined_text)
        sentence_score = ComplexityAnalyzer._calculate_sentence_score(combined_text)
        connector_score = ComplexityAnalyzer._calculate_connector_score(combined_text)
        type_score = ComplexityAnalyzer._calculate_type_score(combined_text)
        
        complexity = (
            0.35 * verb_score +
            0.30 * sentence_score +
            0.20 * connector_score +
            0.15 * type_score
        )
        
        breakdown = {
            "verb_score": verb_score,
            "sentence_score": sentence_score,
            "connector_score": connector_score,
            "type_score": type_score,
            "total": complexity
        }
        
        return complexity, breakdown
    
    @staticmethod
    def _calculate_verb_score(text: str) -> float:
        """计算动词得分（5个动作以上视为最复杂）"""
        verb_count = sum(1 for verb in ComplexityAnalyzer.ACTION_VERBS if verb in text)
        return min(verb_count / 5.0, 1.0)
    
    @staticmethod
    def _calculate_sentence_score(text: str) -> float:
        """计算句子得分（4句话以上视为最复杂）"""
        sentence_count = len(re.split(r'[。；;、,]', text))
        return min(sentence_count / 4.0, 1.0)
    
    @staticmethod
    def _calculate_connector_score(text: str) -> float:
        """计算连接词得分"""
        connector_count = sum(1 for conn in ComplexityAnalyzer.CONNECTORS if conn in text)
        return min(connector_count / 3.0, 1.0)
    
    @staticmethod
    def _calculate_type_score(text: str) -> float:
        """计算文件类型多样性得分（3种以上视为复杂）"""
        type_count = sum(1 for ftype in ComplexityAnalyzer.FILE_TYPES if ftype in text)
        return min(type_count / 3.0, 1.0)

