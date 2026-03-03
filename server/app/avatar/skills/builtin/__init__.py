# app/avatar/skills/builtin/__init__.py

"""
Builtin skills package.
Importing this package registers all builtin skills.
"""

# Core V2 Skills
from . import file  # noqa: F401
from . import system  # noqa: F401
from . import web  # noqa: F401
from . import time  # noqa: F401
from . import llm  # noqa: F401

# Computer Use Skills (GUI Automation)
from . import computer  # noqa: F401

# Extended V2 Skills (Fully Migrated)
from . import directory  # noqa: F401
from . import word  # noqa: F401
from . import excel  # noqa: F401
from . import text  # noqa: F401
from . import pdf  # noqa: F401
from . import http  # noqa: F401
from . import email  # noqa: F401
from . import archive  # noqa: F401
from . import clipboard  # noqa: F401
from . import csv  # noqa: F401
from . import json  # noqa: F401
from . import schedule  # noqa: F401
from . import python  # noqa: F401

#Fallback Skills
from . import fallback

__all__ = [
    "file",
    "system",
    "web",
    "time",
    "llm",  # Added
    "schedule", # Added
    "computer",  # Added
    "directory",
    "word",
    "excel",
    "text",
    "pdf",
    "http",
    "email",
    "archive",
    "clipboard",
    "csv",
    "json",
    "python", # Added
    "fallback",
]
