"""
Two-layer error classification data models.

Layer 1: RuntimeErrorClass (broad category for routing recovery decisions)
Layer 2: ErrorCode (fine-grained code for diagnostics within each class)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Layer 1: RuntimeErrorClass (routing)
# ---------------------------------------------------------------------------


class RuntimeErrorClass(str, Enum):
    """Broad error category used to route recovery decisions."""
    TYPE_MISMATCH = "type_mismatch"
    MISSING_FIELD = "missing_field"
    MISSING_DEPENDENCY = "missing_dependency"
    INVALID_VALUE = "invalid_value"
    SYNTAX_ERROR = "syntax_error"
    EXTERNAL_IO_ERROR = "external_io_error"


# ---------------------------------------------------------------------------
# Layer 2: ErrorCode (diagnostics)
# ---------------------------------------------------------------------------


class ErrorCode(str, Enum):
    """Fine-grained error code within each RuntimeErrorClass."""
    # missing_dependency
    FILE_MISSING = "FILE_MISSING"
    MODULE_MISSING = "MODULE_MISSING"
    IMPORT_FAILED = "IMPORT_FAILED"
    # external_io_error
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DISK_FULL = "DISK_FULL"
    # type_mismatch
    EXPECTED_DICT_GOT_STR = "EXPECTED_DICT_GOT_STR"
    EXPECTED_LIST_GOT_DICT = "EXPECTED_LIST_GOT_DICT"
    SCHEMA_FIELD_MISSING = "SCHEMA_FIELD_MISSING"
    # invalid_value
    JSON_DECODE_FAILED = "JSON_DECODE_FAILED"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
    EMPTY_VALUE = "EMPTY_VALUE"
    # syntax_error
    PYTHON_SYNTAX = "PYTHON_SYNTAX"
    INDENTATION_ERROR = "INDENTATION_ERROR"
    # missing_field
    KEY_NOT_FOUND = "KEY_NOT_FOUND"
    ATTRIBUTE_NOT_FOUND = "ATTRIBUTE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ErrorClassification:
    """Result of classifying a raw exception into the two-layer scheme."""
    error_class: RuntimeErrorClass
    error_code: ErrorCode
    raw_exception_type: str
    raw_message: str
    schema_version: str = "1.0.0"


@dataclass
class RecoveryResult:
    """Recovery decision produced by RecoveryPolicyEngine."""
    error_class: RuntimeErrorClass
    error_code: ErrorCode
    decision: str  # RecoveryDecision value: retry / replan_current_step / replan_subgraph / fail_fast / skip
    override_applied: bool = False  # True if ErrorCode override whitelist was applied
    schema_version: str = "1.0.0"


import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ErrorClassifier
# ---------------------------------------------------------------------------

_EXCEPTION_TYPE_MAP_RESOLVED: Optional[Dict[type, tuple]] = None


def _get_exception_type_map() -> Dict[type, tuple]:
    global _EXCEPTION_TYPE_MAP_RESOLVED
    if _EXCEPTION_TYPE_MAP_RESOLVED is None:
        import json as _json
        _EXCEPTION_TYPE_MAP_RESOLVED = {
            FileNotFoundError: (RuntimeErrorClass.MISSING_DEPENDENCY, ErrorCode.FILE_MISSING),
            ModuleNotFoundError: (RuntimeErrorClass.MISSING_DEPENDENCY, ErrorCode.MODULE_MISSING),
            ImportError: (RuntimeErrorClass.MISSING_DEPENDENCY, ErrorCode.IMPORT_FAILED),
            SyntaxError: (RuntimeErrorClass.SYNTAX_ERROR, ErrorCode.PYTHON_SYNTAX),
            IndentationError: (RuntimeErrorClass.SYNTAX_ERROR, ErrorCode.INDENTATION_ERROR),
            _json.JSONDecodeError: (RuntimeErrorClass.INVALID_VALUE, ErrorCode.JSON_DECODE_FAILED),
        }
    return _EXCEPTION_TYPE_MAP_RESOLVED


# Message patterns → (RuntimeErrorClass, ErrorCode) for message-based refinement
_MESSAGE_PATTERNS = [
    (re.compile(r"permission denied", re.IGNORECASE),
     RuntimeErrorClass.EXTERNAL_IO_ERROR, ErrorCode.PERMISSION_DENIED),
    (re.compile(r"timed?\s*out", re.IGNORECASE),
     RuntimeErrorClass.EXTERNAL_IO_ERROR, ErrorCode.NETWORK_TIMEOUT),
    (re.compile(r"no space left|disk full", re.IGNORECASE),
     RuntimeErrorClass.EXTERNAL_IO_ERROR, ErrorCode.DISK_FULL),
    (re.compile(r"out of range|overflow|underflow", re.IGNORECASE),
     RuntimeErrorClass.INVALID_VALUE, ErrorCode.VALUE_OUT_OF_RANGE),
    (re.compile(r"empty|none.*not allowed|required.*missing", re.IGNORECASE),
     RuntimeErrorClass.INVALID_VALUE, ErrorCode.EMPTY_VALUE),
    # Binary file read/write mismatch — skill used text I/O on a binary format.
    # Route to TYPE_MISMATCH so escalation kicks in after 2 consecutive same-class errors.
    (re.compile(r"cannot read binary file|binary file.*not supported|not a zip file|"
                r"Package not found at|is not a (?:docx|xlsx|pptx|zip) file", re.IGNORECASE),
     RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.SCHEMA_FIELD_MISSING),
]


class ErrorClassifier:
    """Three-phase error classifier: exception type → context refinement → message patterns.

    Usage::

        classifier = ErrorClassifier()
        classification = classifier.classify(exception, context={"source_type": "str", "target_type": "dict"})
    """

    def classify(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
    ) -> ErrorClassification:
        """Classify a raw exception into the two-layer scheme.

        Phase 1: Map exception type to initial (RuntimeErrorClass, ErrorCode).
        Phase 2: Refine using schema/context information (if available).
        Phase 3: Fall back to message pattern matching for unclassified exceptions.
        """
        ctx = context or {}
        raw_type = type(exception).__name__
        raw_msg = str(exception)

        # Phase 1: Exception type mapping
        error_class, error_code = self._classify_by_type(exception)

        # Phase 2: Context-based refinement
        if error_class is not None:
            refined_class, refined_code = self._refine_by_context(
                exception, error_class, error_code, ctx,
            )
            error_class, error_code = refined_class, refined_code
        else:
            # Phase 3: Message pattern matching (only for unclassified)
            error_class, error_code = self._classify_by_message(raw_msg)

        # Final fallback: if still unclassified, use generic invalid_value
        if error_class is None:
            error_class = RuntimeErrorClass.INVALID_VALUE
            error_code = ErrorCode.EMPTY_VALUE

        return ErrorClassification(
            error_class=error_class,
            error_code=error_code,
            raw_exception_type=raw_type,
            raw_message=raw_msg,
        )

    # ------------------------------------------------------------------
    # Phase 1: Exception type
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_by_type(exception: Exception) -> tuple:
        """Map exception type to initial classification. Returns (class, code) or (None, None).

        Subclass checks are ordered most-specific-first to avoid e.g.
        IndentationError being swallowed by the SyntaxError branch.
        """
        # Most-specific subclass checks first
        if isinstance(exception, IndentationError):
            return RuntimeErrorClass.SYNTAX_ERROR, ErrorCode.INDENTATION_ERROR

        type_map = _get_exception_type_map()
        for exc_type, mapping in type_map.items():
            if isinstance(exception, exc_type):
                return mapping

        # Handle KeyError and AttributeError specially — they need context refinement
        if isinstance(exception, KeyError):
            return RuntimeErrorClass.MISSING_FIELD, ErrorCode.KEY_NOT_FOUND
        if isinstance(exception, AttributeError):
            return RuntimeErrorClass.MISSING_FIELD, ErrorCode.ATTRIBUTE_NOT_FOUND
        if isinstance(exception, (TypeError, ValueError)):
            return RuntimeErrorClass.INVALID_VALUE, ErrorCode.EMPTY_VALUE
        if isinstance(exception, (ConnectionError, TimeoutError, OSError)):
            return RuntimeErrorClass.EXTERNAL_IO_ERROR, ErrorCode.NETWORK_TIMEOUT

        return None, None

    # ------------------------------------------------------------------
    # Phase 2: Context refinement
    # ------------------------------------------------------------------

    @staticmethod
    def _refine_by_context(
        exception: Exception,
        error_class: RuntimeErrorClass,
        error_code: ErrorCode,
        ctx: Dict[str, Any],
    ) -> tuple:
        """Refine classification using schema/context information."""
        source_type = ctx.get("source_type", "")
        target_type = ctx.get("target_type", "")
        source_fields = ctx.get("source_fields", [])
        missing_key = ""

        # Extract the missing key from KeyError
        if isinstance(exception, KeyError) and exception.args:
            missing_key = str(exception.args[0])

        # KeyError refinement: is the key in the source schema?
        if isinstance(exception, KeyError):
            if source_fields and missing_key not in source_fields:
                return RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.SCHEMA_FIELD_MISSING
            return RuntimeErrorClass.MISSING_FIELD, ErrorCode.KEY_NOT_FOUND

        # AttributeError refinement: str upstream + dict expected downstream
        if isinstance(exception, AttributeError):
            msg = str(exception)
            if source_type == "str" and target_type == "dict":
                return RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.EXPECTED_DICT_GOT_STR
            if "'str' object" in msg and ("keys" in msg or "items" in msg or "get" in msg):
                return RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.EXPECTED_DICT_GOT_STR
            if "'list' object" in msg and target_type == "dict":
                return RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.EXPECTED_LIST_GOT_DICT

        # TypeError refinement: type mismatch patterns
        if isinstance(exception, (TypeError, ValueError)):
            msg = str(exception)
            if source_type and target_type and source_type != target_type:
                if target_type == "dict" and source_type == "str":
                    return RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.EXPECTED_DICT_GOT_STR
                if target_type == "list" and source_type == "dict":
                    return RuntimeErrorClass.TYPE_MISMATCH, ErrorCode.EXPECTED_LIST_GOT_DICT

        return error_class, error_code

    # ------------------------------------------------------------------
    # Phase 3: Message pattern matching
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_by_message(message: str) -> tuple:
        """Fall back to regex pattern matching on the error message."""
        for pattern, error_class, error_code in _MESSAGE_PATTERNS:
            if pattern.search(message):
                return error_class, error_code
        return None, None
