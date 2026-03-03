# server/app/router/classifier.py
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class IntentClassifier:
    """
    【第一层】意图分类器 - 快速轻量级判断
    
    职责：快速判断用户输入是 "chat" 还是 "task"
    
    特点：
    - 超轻量 prompt（约 15 行）
    - 无需技能列表
    - 无需历史对话
    - 快速返回，节省 token
    
    设计理念：
    如果是明显的闲聊，直接返回 chat，避免调用重量级的任务理解模块。
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self._llm = llm_client

    # ---- 关键词快速路径（跳过 LLM 调用） ----
    _CHAT_KEYWORDS = {
        # 中文问候/闲聊
        "你好", "您好", "嗨", "早上好", "晚上好", "下午好", "谢谢", "感谢",
        "再见", "拜拜", "你是谁", "你叫什么", "你能做什么",
        # 英文问候/闲聊
        "hello", "hi", "hey", "good morning", "good night", "thanks", "thank you",
        "bye", "goodbye", "who are you", "what can you do",
    }
    
    _TASK_PREFIXES_ZH = [
        "帮我", "帮忙", "请帮", "创建", "打开", "关闭", "删除", "下载",
        "搜索", "查找", "运行", "执行", "安装", "写一个", "生成",
        "发送", "复制", "移动", "重命名", "压缩", "解压", "截图",
        "打开网页", "打开浏览器", "打开文件",
    ]
    
    _TASK_PREFIXES_EN = [
        "open ", "create ", "delete ", "run ", "execute ", "install ",
        "download ", "search ", "find ", "send ", "copy ", "move ",
        "rename ", "compress ", "extract ", "screenshot", "browse ",
    ]

    def is_task_intent(self, text: str) -> bool:
        """
        Classify user intent as chat or task.
        Uses keyword fast-path first, falls back to LLM.
        Returns: True if potential task, False if likely chat.
        """
        text = text.strip()
        logger.debug(f"IntentClassifier: Checking intent for: '{text[:50]}...'")

        if not text:
            return False

        text_lower = text.lower()
        
        # Fast path 1: 精确匹配闲聊关键词
        if text_lower in self._CHAT_KEYWORDS:
            logger.info(f"IntentClassifier: Fast-path CHAT (keyword match) for '{text[:20]}...'")
            return False
        
        # Fast path 2: 前缀匹配任务关键词（中文）
        for prefix in self._TASK_PREFIXES_ZH:
            if text.startswith(prefix):
                logger.info(f"IntentClassifier: Fast-path TASK (prefix '{prefix}') for '{text[:20]}...'")
                return True
        
        # Fast path 3: 前缀匹配任务关键词（英文）
        for prefix in self._TASK_PREFIXES_EN:
            if text_lower.startswith(prefix):
                logger.info(f"IntentClassifier: Fast-path TASK (prefix '{prefix}') for '{text[:20]}...'")
                return True

        # Use LLM classification
        if self._llm:
            try:
                classification = self._llm_classify(text)
                logger.debug(f"IntentClassifier: LLM returned: '{classification}' for '{text[:30]}...'")

                if classification == "task":
                    logger.info(f"IntentClassifier: LLM classified '{text[:20]}...' as TASK")
                    return True
                elif classification == "chat":
                    logger.info(f"IntentClassifier: LLM classified '{text[:20]}...' as CHAT")
                    return False
                else:
                    logger.warning(f"IntentClassifier: LLM returned invalid classification: {classification}")
            except Exception as e:
                logger.warning(f"IntentClassifier: LLM classification failed: {e}")

        # If LLM fails, default to chat (safer for our use case)
        logger.info(f"IntentClassifier: LLM unavailable or failed, defaulting to chat for '{text[:20]}...'")
        return False

    def _llm_classify(self, text: str) -> str:
        """
        Use LLM to classify intent as "chat" or "task".
        Lightweight prompt optimized for speed.
        """
        prompt = f"""Classify as "chat" or "task":

- chat: Conversation, knowledge questions, greetings
- task: Actions, real-time data, system operations

Examples:
"Hello" -> chat
"What is Python?" -> chat
"Create a file" -> task
"What time is it?" -> task

User: {text}

Output (only "chat" or "task"):"""

        try:
            # Use the LLM client's call method (assuming it exists)
            if hasattr(self._llm, 'call'):
                response = self._llm.call(prompt)
            elif hasattr(self._llm, 'generate'):
                response = self._llm.generate(prompt)
            else:
                response = str(self._llm(prompt))

            result = response.strip().lower()
            logger.info(f"IntentClassifier: LLM raw response for '{text[:20]}...': '{result[:100]}'")

            # Simple keyword extraction
            if "task" in result:
                return "task"
            elif "chat" in result:
                return "chat"
            else:
                # Try first word
                first_word = result.split()[0] if result.split() else ""
                logger.info(f"IntentClassifier: Using first word: '{first_word}'")
                if first_word in ["task", "chat"]:
                    return first_word

        except Exception as e:
            logger.error(f"LLM classification error: {e}")

        # Return empty if failed - will fallback to default (task)
        return ""

