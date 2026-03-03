from pydantic import model_validator

class ContentRobustnessMixin:
    """
    Mixin for handling dict inputs for 'content' field robustness.
    
    Expects the consuming model to define:
    - content: str
    """

    @model_validator(mode="before")
    def handle_content_dict_inputs(cls, values):
        """
        鲁棒性处理：如果 LLM 错误地将上游 SkillOutput（字典）传给 content，
        尝试提取有效数据。
        """
        # 1. 识别是否传入了 dict 类型的 content
        if not isinstance(values, dict):
            return values

        if "content" in values and isinstance(values["content"], dict):
            incoming_dict = values["content"]
            
            # 策略 1: 检查是否有 'content' 字段 (针对 file.read, llm.generate_text 等)
            if "content" in incoming_dict and isinstance(incoming_dict["content"], str):
                 logger.debug(f"{cls.__name__}: Auto-extracted 'content' from dict input")
                 values["content"] = incoming_dict["content"]
                 return values
            
            # 策略 2: 检查是否有 'text' 字段 (针对 llm.generate_text)
            if "text" in incoming_dict and isinstance(incoming_dict["text"], str):
                 logger.debug(f"{cls.__name__}: Auto-extracted 'text' from dict input as content")
                 values["content"] = incoming_dict["text"]
                 return values
                 
            # 策略 3: 检查是否有 'data' 字段 (通用)
            if "data" in incoming_dict and isinstance(incoming_dict["data"], str):
                 logger.debug(f"{cls.__name__}: Auto-extracted 'data' from dict input as content")
                 values["content"] = incoming_dict["data"]
                 return values

            logger.debug(f"{cls.__name__}: Warning - received dict for content, but no extractable text found. {incoming_dict.keys()}")
            
        return values

