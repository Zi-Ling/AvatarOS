from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from app.avatar.skills.registry import skill_registry

router = APIRouter(prefix="/api/skills", tags=["skills"])

@router.get("/", response_model=Dict[str, Any])
async def list_skills():
    """
    List all available skills with their metadata/schema.
    This is used by the frontend 'Library' tab to show capabilities.
    """
    try:
        return skill_registry.describe_skills()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/categories", response_model=List[str])
async def list_categories():
    """List all unique skill categories."""
    specs = skill_registry.list_specs()
    categories = set()
    for s in specs:
        if not s.category:
            continue
        # Handle both Enum and str
        if hasattr(s.category, 'value'):
            categories.add(s.category.value)
        else:
            categories.add(str(s.category))
            
    return sorted(list(categories))

