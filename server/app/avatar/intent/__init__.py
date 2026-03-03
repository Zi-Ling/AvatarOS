# app/avatar/intent/__init__.py
from .models import IntentSpec
from .compiler import IntentExtractor

__all__ = ["IntentSpec", "IntentExtractor"]
