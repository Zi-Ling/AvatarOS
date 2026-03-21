"""
Two-layer conversation summary for long-context preservation.

Layer 1 — Fact summary (structured):
  - User goals, produced artifacts, key constraints, pending items
  - Preserved as structured dict, not lossy natural language

Layer 2 — Dialogue summary (natural language):
  - Background context, casual exchanges, non-critical info
  - Compressed into a short paragraph

The summary is stored in MemoryManager working state and updated
incrementally every N messages (not every Planner call).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How many new messages trigger a summary update
SUMMARY_UPDATE_INTERVAL = 8


def get_conversation_summary(
    memory_manager: Any,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve the stored conversation summary for a session."""
    key = f"conv:{session_id}:summary"
    return memory_manager.get_working_state(key)


def should_update_summary(
    memory_manager: Any,
    session_id: str,
    current_message_count: int,
) -> bool:
    """Check if the summary needs updating based on message count delta."""
    existing = get_conversation_summary(memory_manager, session_id)
    if existing is None:
        return current_message_count >= SUMMARY_UPDATE_INTERVAL
    last_count = existing.get("last_message_count", 0)
    return (current_message_count - last_count) >= SUMMARY_UPDATE_INTERVAL


def build_summary_from_history(
    messages: List[Dict[str, Any]],
    existing_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a two-layer summary from chat history.

    This is a rule-based extraction (no LLM call) that pulls structured
    facts from task_result messages and compresses older dialogue.

    Returns:
        {
            "facts": {
                "goals": [...],
                "artifacts": [...],
                "constraints": [...],
                "pending": [...]
            },
            "dialogue_summary": "...",
            "last_message_count": N
        }
    """
    facts = {
        "goals": list((existing_summary or {}).get("facts", {}).get("goals", [])),
        "artifacts": list((existing_summary or {}).get("facts", {}).get("artifacts", [])),
        "constraints": list((existing_summary or {}).get("facts", {}).get("constraints", [])),
        "pending": [],
    }
    dialogue_parts = []

    # Determine which messages are new (not yet summarized)
    last_count = (existing_summary or {}).get("last_message_count", 0)
    new_messages = messages[last_count:]

    for msg in new_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        meta = msg.get("metadata", {}) or {}
        msg_type = meta.get("message_type", "chat")

        if role == "user" and content.strip():
            # Extract user goals from their messages (first 100 chars)
            goal_text = content.strip()[:100]
            if goal_text and goal_text not in facts["goals"]:
                facts["goals"].append(goal_text)
                # Keep only last 10 goals
                facts["goals"] = facts["goals"][-10:]

        elif role == "assistant" and msg_type == "task_result":
            # Structured task result — extract artifacts and status
            output_path = meta.get("output_path", "")
            status = meta.get("status", "")
            goal = meta.get("goal", "")

            if output_path:
                artifact_entry = f"{goal}: {output_path} ({status})"
                if artifact_entry not in facts["artifacts"]:
                    facts["artifacts"].append(artifact_entry)
                    facts["artifacts"] = facts["artifacts"][-15:]

            if status == "failed" and goal:
                facts["pending"].append(f"Failed: {goal[:80]}")

        elif role == "assistant" and content.strip():
            # Regular assistant message — compress for dialogue summary
            snippet = content.strip()[:120]
            dialogue_parts.append(snippet)

    # Build dialogue summary from recent non-task messages
    dialogue_summary = (existing_summary or {}).get("dialogue_summary", "")
    if dialogue_parts:
        new_dialogue = " | ".join(dialogue_parts[-5:])
        if dialogue_summary:
            # Append new, keep total under 500 chars
            combined = f"{dialogue_summary} | {new_dialogue}"
            dialogue_summary = combined[-500:]
        else:
            dialogue_summary = new_dialogue[-500:]

    return {
        "facts": facts,
        "dialogue_summary": dialogue_summary,
        "last_message_count": len(messages),
    }


def save_conversation_summary(
    memory_manager: Any,
    session_id: str,
    summary: Dict[str, Any],
) -> None:
    """Persist the conversation summary."""
    key = f"conv:{session_id}:summary"
    memory_manager.set_working_state(key, summary)


def format_summary_for_prompt(summary: Dict[str, Any]) -> str:
    """Format the two-layer summary as a prompt section."""
    if not summary:
        return ""

    lines = ["## Conversation Memory (summarized from earlier messages)"]

    facts = summary.get("facts", {})
    goals = facts.get("goals", [])
    artifacts = facts.get("artifacts", [])
    pending = facts.get("pending", [])

    if goals:
        lines.append("### User Goals")
        for g in goals[-5:]:
            lines.append(f"  - {g}")

    if artifacts:
        lines.append("### Produced Artifacts")
        for a in artifacts[-5:]:
            lines.append(f"  - {a}")

    if pending:
        lines.append("### Pending / Failed")
        for p in pending[-3:]:
            lines.append(f"  - {p}")

    dialogue = summary.get("dialogue_summary", "")
    if dialogue:
        lines.append(f"### Background Context\n{dialogue}")

    return "\n".join(lines) + "\n"
