# app/api/learning/router.py
"""
学习结果查询接口
"""
from fastapi import APIRouter, Depends
from typing import Dict, List, Any

from app.avatar.learning import LearningManager
from app.core.dependencies import get_learning_manager


router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/samples")
async def get_learning_samples(
    learning_mgr: LearningManager = Depends(get_learning_manager),
) -> Dict[str, Any]:
    """
    获取所有学习样本（来自 InMemoryNotebook）
    
    用途：调试学习链路，查看系统学到了什么
    """
    notebook = learning_mgr._modules.get("in_memory_notebook")
    if not notebook:
        return {"samples": [], "message": "InMemoryNotebook 未注册"}
    
    samples = notebook.samples
    
    # 格式化样本（只返回必要信息）
    formatted_samples = []
    for sample in samples[-50:]:  # 只返回最近 50 条
        formatted_samples.append({
            "kind": sample.kind,
            "input_data": sample.input_data,
            "metadata": sample.metadata,
        })
    
    return {
        "total_count": len(samples),
        "showing": len(formatted_samples),
        "samples": formatted_samples,
    }


@router.get("/skills/stats")
async def get_skill_stats(
    learning_mgr: LearningManager = Depends(get_learning_manager),
) -> Dict[str, Any]:
    """
    获取技能统计数据（来自 SkillStatsLearner）
    
    用途：监控技能质量，发现问题技能
    """
    stats_learner = learning_mgr._modules.get("skill_stats")
    if not stats_learner:
        return {"skills": [], "message": "SkillStatsLearner 未注册"}
    
    stats = stats_learner.stats_snapshot
    
    # 格式化统计数据
    skills_stats = []
    for skill_name, stat in stats.items():
        skills_stats.append({
            "name": stat.name,
            "total": stat.total,
            "success": stat.success,
            "failed": stat.failed,
            "success_rate": round(stat.success_rate * 100, 1),  # 百分比
            "last_error": stat.last_error,
        })
    
    # 按失败次数排序（问题技能优先）
    skills_stats.sort(key=lambda x: x["failed"], reverse=True)
    
    return {
        "total_skills": len(skills_stats),
        "skills": skills_stats,
    }


@router.get("/user/preferences")
async def get_all_user_preferences(
    learning_mgr: LearningManager = Depends(get_learning_manager),
) -> Dict[str, Any]:
    """
    获取所有用户的偏好设置（来自 UserPreferenceLearner）
    
    用途：查看系统学到的用户习惯
    """
    pref_learner = learning_mgr._modules.get("user_preference")
    if not pref_learner:
        return {"users": {}, "message": "UserPreferenceLearner 未注册"}
    
    # 访问内部缓存
    prefs_cache = pref_learner._prefs_cache
    
    return {
        "total_users": len(prefs_cache),
        "users": prefs_cache,
    }


@router.get("/user/{user_id}/preferences")
async def get_user_preferences(
    user_id: str,
    learning_mgr: LearningManager = Depends(get_learning_manager),
) -> Dict[str, Any]:
    """
    获取特定用户的偏好设置
    
    用途：查看单个用户的个性化配置
    """
    pref_learner = learning_mgr._modules.get("user_preference")
    if not pref_learner:
        return {"preferences": None, "message": "UserPreferenceLearner 未注册"}
    
    prefs = pref_learner.get_prefs(user_id)
    
    if prefs is None:
        return {
            "user_id": user_id,
            "preferences": None,
            "message": "该用户暂无偏好记录",
        }
    
    return {
        "user_id": user_id,
        "preferences": prefs,
    }


@router.get("/summary")
async def get_learning_summary(
    learning_mgr: LearningManager = Depends(get_learning_manager),
) -> Dict[str, Any]:
    """
    获取学习系统的整体摘要
    
    用途：快速了解学习系统状态
    """
    summary = {
        "registered_modules": learning_mgr.list_modules(),
        "statistics": {},
    }
    
    # InMemoryNotebook 统计
    notebook = learning_mgr._modules.get("in_memory_notebook")
    if notebook:
        samples = notebook.samples
        summary["statistics"]["total_samples"] = len(samples)
        summary["statistics"]["sample_types"] = {}
        for sample in samples:
            kind = sample.kind
            summary["statistics"]["sample_types"][kind] = summary["statistics"]["sample_types"].get(kind, 0) + 1
    
    # SkillStatsLearner 统计
    stats_learner = learning_mgr._modules.get("skill_stats")
    if stats_learner:
        stats = stats_learner.stats_snapshot
        total_calls = sum(s.total for s in stats.values())
        total_successes = sum(s.success for s in stats.values())
        total_failures = sum(s.failed for s in stats.values())
        
        summary["statistics"]["skills"] = {
            "total_skills": len(stats),
            "total_calls": total_calls,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_success_rate": round(total_successes / total_calls * 100, 1) if total_calls > 0 else 0,
        }
    
    # UserPreferenceLearner 统计
    pref_learner = learning_mgr._modules.get("user_preference")
    if pref_learner:
        prefs_cache = pref_learner._prefs_cache
        summary["statistics"]["users_with_preferences"] = len(prefs_cache)
    
    return summary

