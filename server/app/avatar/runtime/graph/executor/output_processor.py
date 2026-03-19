"""
Output processing mixin for GraphExecutor.

Handles output contract processing, schema writing, artifact registration,
and semantic metadata extraction after node execution.

Extracted from graph_executor.py to keep the executor module focused on
core execution logic.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import json
import logging
from pathlib import Path

from app.avatar.runtime.graph.models.output_contract import (
    TransportMode,
    ValueKind,
    ArtifactRole,
    InvalidTransportError,
)

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class OutputProcessorMixin:
    """Mixin providing output processing methods for GraphExecutor."""

    async def _process_output_contract(
        self,
        node: 'StepNode',
        outputs: Dict[str, Any],
        context: Optional['ExecutionContext'],
    ) -> None:
        """
        P0: Process SkillOutputContract after node execution.
        1. Adapt raw output to SkillOutputContract via OutputContractAdapter
        2. Reject BINARY+INLINE, record invalid_transport event
        3. Register PRODUCED+ARTIFACT outputs in ArtifactRegistry
        4. Store contract in node.metadata["output_contract"]
        """
        session_id = None
        if context:
            session_id = (
                (context.env.get("exec_session_id") if isinstance(getattr(context, "env", None), dict) else None)
                or getattr(getattr(context, "identity", None), "session_id", None)
                or (context.variables.get("session_id") if hasattr(context, "variables") else None)
            )

        try:
            contract = self._output_contract_adapter.adapt(
                raw_output=outputs,
                mode=self.output_compat_mode,
                trace_store=self.trace_store,
                session_id=session_id,
            )
        except InvalidTransportError as e:
            # BINARY+INLINE: record event and skip
            logger.warning(f"[GraphExecutor] Node {node.id}: {e}")
            if self.trace_store and session_id:
                try:
                    self.trace_store.record_event(
                        session_id=session_id,
                        event_type="invalid_transport",
                        payload={
                            "node_id": node.id,
                            "reason": str(e),
                            "output_keys": list(outputs.keys()),
                        },
                    )
                except Exception:
                    pass
            return
        except Exception as e:
            logger.warning(f"[GraphExecutor] Node {node.id} output contract adapt failed: {e}")
            return

        if node.metadata is None:
            node.metadata = {}
        node.metadata["output_contract"] = contract

        # Register artifact if role=PRODUCED and transport=ARTIFACT
        if (
            contract.artifact_role == ArtifactRole.PRODUCED
            and contract.transport_mode == TransportMode.ARTIFACT
            and self.artifact_registry
        ):
            await self._register_artifact(node, outputs, contract, session_id)

    def _write_output_schema(self, node: 'StepNode', outputs: Dict[str, Any]) -> None:
        """Write StepOutputSchema to node.metadata['output_schema'].

        Tries SchemaRegistry first, falls back to inference from actual outputs.
        """
        try:
            from app.avatar.runtime.graph.registry.schema_registry import SchemaRegistry
            from app.avatar.runtime.graph.types.schema import (
                FieldSchema, StepOutputSchema, ValueKind as TypedValueKind,
            )

            registry = SchemaRegistry()
            schema = registry.get_output_schema(node.capability_name)
            if schema is None:
                # Infer from actual outputs
                fields = []
                for k, v in outputs.items():
                    if k.startswith("_"):
                        continue
                    ft = type(v).__name__
                    fields.append(FieldSchema(field_name=k, field_type=ft))
                kind = TypedValueKind.JSON
                if isinstance(outputs.get("result"), str) or isinstance(outputs.get("output"), str):
                    kind = TypedValueKind.TEXT
                schema = StepOutputSchema(semantic_kind=kind, fields=fields)

            if node.metadata is None:
                node.metadata = {}
            node.metadata["output_schema"] = {
                "semantic_kind": schema.semantic_kind.value,
                "fields": [{"field_name": f.field_name, "field_type": f.field_type}
                           for f in schema.fields],
            }
        except Exception as e:
            logger.debug("[GraphExecutor] _write_output_schema failed: %s", e)

    def _write_input_schema(self, node: 'StepNode') -> None:
        """Write SkillInputSchema to node.metadata['input_schema']."""
        try:
            from app.avatar.runtime.graph.registry.schema_registry import SchemaRegistry

            registry = SchemaRegistry()
            schema = registry.get_input_schema(node.capability_name)
            if schema is not None:
                if node.metadata is None:
                    node.metadata = {}
                node.metadata["input_schema"] = {
                    "skill_name": schema.skill_name,
                    "params": [
                        {"param_name": p.param_name, "expected_kind": p.expected_kind.value,
                         "expected_python_type": p.expected_python_type,
                         "accepts_envelope": p.accepts_envelope}
                        for p in schema.params
                    ],
                }
        except Exception as e:
            logger.debug("[GraphExecutor] _write_input_schema failed: %s", e)

    async def _register_artifact(
        self,
        node: 'StepNode',
        outputs: Dict[str, Any],
        contract: Any,
        session_id: Optional[str],
    ) -> None:
        """Register a PRODUCED+ARTIFACT output in ArtifactRegistry."""
        try:
            from app.avatar.runtime.artifact.registry import ArtifactType

            # Determine file path from outputs
            path = (
                outputs.get("file_path")
                or outputs.get("output_path")
                or outputs.get("path")
            )
            if not path:
                logger.debug(f"[GraphExecutor] Node {node.id}: no path found for artifact registration")
                return

            # Map ValueKind to ArtifactType
            vk_to_type = {
                ValueKind.BINARY: ArtifactType.BINARY,
                ValueKind.JSON: ArtifactType.JSON_BLOB,
                ValueKind.TABLE: ArtifactType.TABLE,
                ValueKind.TEXT: ArtifactType.FILE,
                ValueKind.PATH: ArtifactType.FILE,
            }
            artifact_type = vk_to_type.get(contract.value_kind, ArtifactType.FILE)
            if contract.mime_type and contract.mime_type.startswith("image/"):
                artifact_type = ArtifactType.IMAGE

            artifact = self.artifact_registry.register(
                path=str(path),
                producer_step=node.id,
                artifact_type=artifact_type,
                semantic_label=contract.semantic_label,
            )
            # Store artifact_id back into contract and node metadata
            contract.artifact_id = artifact.id
            if node.metadata is None:
                node.metadata = {}
            node.metadata["artifact_id"] = artifact.id
            logger.debug(f"[GraphExecutor] Node {node.id}: registered artifact {artifact.id}")
        except Exception as e:
            logger.warning(f"[GraphExecutor] Node {node.id}: artifact registration failed: {e}")

    # ── P1-4: Artifact semantic metadata ────────────────────────────────
    _ARTIFACT_EXT_TYPES = {
        ".png": "chart_image", ".jpg": "image", ".jpeg": "image",
        ".svg": "vector_image", ".gif": "image",
        ".csv": "table_data", ".xlsx": "spreadsheet", ".xls": "spreadsheet",
        ".json": "structured_data", ".md": "document", ".txt": "document",
        ".html": "document", ".pdf": "document",
    }

    def _extract_artifact_semantic(
        self, node: 'StepNode', outputs: Dict[str, Any],
        host_workspace: Optional[str] = None,
        session_root: Optional[str] = None,
    ) -> None:
        """Attach semantic metadata to node for file-producing skills."""
        import re
        try:
            from app.avatar.runtime.workspace.path_canonical import canonicalize_path

            # Collect file paths from outputs
            _raw = outputs.get("stdout") or outputs.get("output") or outputs.get("result") or ""
            if isinstance(_raw, dict):
                _raw = json.dumps(_raw)
            elif not isinstance(_raw, str):
                _raw = str(_raw)

            _path_pattern = re.compile(
                r'(/[\w./ -]+\.(?:png|jpg|jpeg|svg|gif|csv|xlsx|xls|json|md|txt|html|pdf))',
                re.IGNORECASE,
            )
            found_paths = _path_pattern.findall(_raw)

            # Also check explicit output keys
            for key in ("file_path", "output_path", "path"):
                val = outputs.get(key)
                if isinstance(val, str) and val not in found_paths:
                    found_paths.append(val)

            if not found_paths:
                return

            if node.metadata is None:
                node.metadata = {}

            artifacts_semantic = []
            for fp in found_paths:
                # Canonicalize container paths to host paths
                canonical_fp = canonicalize_path(
                    fp,
                    host_workspace=host_workspace,
                    session_root=session_root,
                )
                ext = Path(canonical_fp).suffix.lower()
                art_type = self._ARTIFACT_EXT_TYPES.get(ext, "file")

                desc = ""
                node_meta = node.metadata or {}
                if node_meta.get("description"):
                    desc = str(node_meta["description"])
                elif (node.params or {}).get("description"):
                    desc = str(node.params["description"])
                elif (node.params or {}).get("goal"):
                    desc = str(node.params["goal"])

                code = (node.params or {}).get("code") or (node.params or {}).get("script") or ""
                data_sources = re.findall(r'step_\d+_output', code) if isinstance(code, str) else []

                artifacts_semantic.append({
                    "path": canonical_fp,
                    "artifact_type": art_type,
                    "source_description": desc[:200] if desc else "",
                    "data_source_steps": list(set(data_sources)),
                })

            node.metadata["artifact_semantic"] = artifacts_semantic
            logger.debug(
                f"[GraphExecutor] Node {node.id}: extracted semantic metadata "
                f"for {len(artifacts_semantic)} artifact(s)"
            )
        except Exception as e:
            logger.debug(f"[GraphExecutor] Node {node.id}: artifact semantic extraction failed: {e}")
