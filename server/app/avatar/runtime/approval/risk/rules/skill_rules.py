"""
技能级别风险规则
"""
from typing import Dict
from ..levels import RiskLevel


# 技能风险等级映射
SKILL_RISK_RULES: Dict[str, RiskLevel] = {
    # LOW - 只读操作
    "file.read": RiskLevel.LOW,
    "file.read_text": RiskLevel.LOW,
    "file.list": RiskLevel.LOW,
    "web.get": RiskLevel.LOW,
    "web.search": RiskLevel.LOW,
    "time.get": RiskLevel.LOW,
    "text.split": RiskLevel.LOW,
    "text.join": RiskLevel.LOW,
    "json.parse": RiskLevel.LOW,
    
    # MEDIUM - 可逆修改
    "file.write": RiskLevel.MEDIUM,
    "file.write_text": RiskLevel.MEDIUM,
    "file.create": RiskLevel.MEDIUM,
    "file.copy": RiskLevel.MEDIUM,
    "web.post": RiskLevel.MEDIUM,
    "email.send": RiskLevel.MEDIUM,
    
    # HIGH - 不可逆操作
    "file.delete": RiskLevel.HIGH,
    "file.move": RiskLevel.HIGH,
    "system.execute": RiskLevel.HIGH,
    "database.delete": RiskLevel.HIGH,
    "web.delete": RiskLevel.HIGH,
    
    # CRITICAL - 系统级操作
    "system.sudo": RiskLevel.CRITICAL,
    "database.drop": RiskLevel.CRITICAL,
    "system.shutdown": RiskLevel.CRITICAL,
}


def get_skill_risk(skill_name: str) -> RiskLevel:
    """
    获取技能的风险等级
    
    Args:
        skill_name: 技能名称
    
    Returns:
        RiskLevel: 风险等级，默认 MEDIUM
    """
    return SKILL_RISK_RULES.get(skill_name, RiskLevel.MEDIUM)

