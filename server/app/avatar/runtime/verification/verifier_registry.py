"""
VerifierRegistry — registration and lookup of verifiers.

Auto-registers the five built-in verifiers on instantiation.
Supports domain packs for extensibility.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from app.avatar.runtime.verification.models import (
    NormalizedGoal,
    VerificationTarget,
    VerifierConditionType,
)
from app.avatar.runtime.verification.verifiers.base import BaseVerifier

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DomainVerifierPack(ABC):
    """Base class for domain-specific verifier packs."""

    @abstractmethod
    def get_verifiers(self) -> List[Type[BaseVerifier]]:
        """Return list of verifier classes provided by this pack."""
        ...


class VerifierRegistry:
    """
    Registry for verifiers.

    Usage:
        registry = VerifierRegistry()  # auto-registers built-ins
        verifiers = registry.get_verifiers(normalized_goal, targets)
    """

    def __init__(self) -> None:
        # condition_type → list of verifier instances
        self._by_condition: Dict[VerifierConditionType, List[BaseVerifier]] = {}
        # all registered verifier instances (ordered by priority)
        self._all: List[BaseVerifier] = []
        self._register_builtins()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, verifier_cls: Type[BaseVerifier]) -> None:
        """Register a verifier class (instantiates it)."""
        instance = verifier_cls()
        ctype = instance.spec.condition_type
        if ctype not in self._by_condition:
            self._by_condition[ctype] = []
        self._by_condition[ctype].append(instance)
        self._all.append(instance)
        # Keep sorted by priority (higher = earlier)
        self._all.sort(key=lambda v: v.spec.priority, reverse=True)
        logger.debug(f"[VerifierRegistry] Registered: {instance.spec.name} ({ctype})")

    def load_domain_pack(self, pack: "Any") -> None:
        """
        Load verifiers from a DomainPack (new dataclass) or DomainVerifierPack (legacy ABC).
        Records domain_pack_loaded event if trace_store is available.
        """
        # New DomainPack dataclass (P3)
        if hasattr(pack, "verifier_pack") and isinstance(pack.verifier_pack, dict):
            pack_id = getattr(pack, "pack_id", pack.__class__.__name__)
            for name, verifier_instance in pack.verifier_pack.items():
                # Track which pack registered which verifier names
                if not hasattr(self, "_pack_verifier_names"):
                    self._pack_verifier_names: Dict[str, List[str]] = {}
                self._pack_verifier_names.setdefault(pack_id, []).append(name)
                # Register instance directly if it's a BaseVerifier
                if isinstance(verifier_instance, BaseVerifier):
                    ctype = verifier_instance.spec.condition_type
                    self._by_condition.setdefault(ctype, []).append(verifier_instance)
                    self._all.append(verifier_instance)
                    self._all.sort(key=lambda v: v.spec.priority, reverse=True)
            logger.info(f"[VerifierRegistry] Loaded DomainPack: {pack_id} ({len(pack.verifier_pack)} verifiers)")
            return

        # Legacy DomainVerifierPack ABC
        for cls in pack.get_verifiers():
            self.register(cls)
        logger.info(f"[VerifierRegistry] Loaded domain pack: {pack.__class__.__name__}")

    def unload_domain_pack(self, pack: "Any") -> None:
        """
        Unload verifiers registered by a DomainPack.
        Does not affect verifiers from other packs.
        Records domain_pack_unloaded event.
        """
        pack_id = getattr(pack, "pack_id", None)
        if pack_id is None:
            logger.warning("[VerifierRegistry] unload_domain_pack: pack has no pack_id, skipping")
            return

        pack_names = getattr(self, "_pack_verifier_names", {}).get(pack_id, [])
        if not pack_names:
            logger.info(f"[VerifierRegistry] unload_domain_pack: no verifiers tracked for {pack_id}")
            return

        # Remove from _all and _by_condition
        self._all = [v for v in self._all if v.spec.name not in pack_names]
        for ctype in list(self._by_condition.keys()):
            self._by_condition[ctype] = [
                v for v in self._by_condition[ctype] if v.spec.name not in pack_names
            ]
        # Clear tracking
        if hasattr(self, "_pack_verifier_names"):
            self._pack_verifier_names.pop(pack_id, None)

        logger.info(f"[VerifierRegistry] Unloaded DomainPack: {pack_id} ({len(pack_names)} verifiers removed)")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_verifiers(
        self,
        normalized_goal: NormalizedGoal,
        targets: List[VerificationTarget],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[BaseVerifier]:
        """
        Assemble verifiers for the given goal and targets.

        Phase 1: matches on normalized_goal.verification_intents and target.mime_type.
        Phase 2: context parameter enables dynamic assembly based on recent steps
                 and output contract types from the execution graph.
        Phase 3 (P0): auto-select verifiers based on SkillOutputContract.value_kind.

        Returns deduplicated list ordered by priority.
        """
        selected: List[BaseVerifier] = []
        seen_names: set = set()

        def _add(v: BaseVerifier) -> None:
            if v.spec.name not in seen_names:
                selected.append(v)
                seen_names.add(v.spec.name)

        # 1. Match on verification_intents
        for intent in normalized_goal.verification_intents:
            try:
                ctype = VerifierConditionType(intent)
                for v in self._by_condition.get(ctype, []):
                    _add(v)
            except ValueError:
                logger.debug(f"[VerifierRegistry] Unknown intent: {intent}")

        # 2. Match on target mime_type
        for target in targets:
            if target.mime_type:
                for v in self._all:
                    if self._mime_matches(target.mime_type, v.spec.condition_type):
                        _add(v)

        # 3. Phase 2: dynamic assembly from context (recent succeeded steps + output contracts)
        if context:
            graph = context.get("graph")
            if graph is not None:
                self._add_from_graph_context(graph, _add)

            # P0: auto-select based on SkillOutputContract.value_kind
            output_contracts = context.get("output_contracts") or {}
            for contract in output_contracts.values():
                self._add_from_output_contract(contract, _add)

        # 4. Always include FileExistsVerifier for file targets if not already added
        has_file_targets = any(t.kind == "file" for t in targets)
        if has_file_targets:
            for v in self._by_condition.get(VerifierConditionType.FILE_EXISTS, []):
                _add(v)

        logger.debug(
            f"[VerifierRegistry] Assembled {len(selected)} verifier(s) for "
            f"intents={normalized_goal.verification_intents}"
        )
        return selected

    def _add_from_output_contract(self, contract: Any, add_fn) -> None:
        """
        P0: Auto-select verifiers based on SkillOutputContract.value_kind + transport_mode.
        - value_kind=BINARY + transport_mode=ARTIFACT → ImageOpenableVerifier
        - value_kind=JSON → JsonParseableVerifier
        """
        try:
            from app.avatar.runtime.graph.models.output_contract import ValueKind, TransportMode
            vk = getattr(contract, "value_kind", None)
            tm = getattr(contract, "transport_mode", None)
            if vk == ValueKind.BINARY and tm == TransportMode.ARTIFACT:
                for v in self._by_condition.get(VerifierConditionType.IMAGE_OPENABLE, []):
                    add_fn(v)
            elif vk == ValueKind.JSON:
                for v in self._by_condition.get(VerifierConditionType.JSON_PARSEABLE, []):
                    add_fn(v)
        except Exception as e:
            logger.debug(f"[VerifierRegistry] output contract assembly failed: {e}")

    def _add_from_graph_context(self, graph: Any, add_fn) -> None:
        """
        Phase 2: inspect recently succeeded graph nodes' output contracts
        to dynamically add appropriate verifiers.
        """
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            succeeded = [
                n for n in graph.nodes.values()
                if n.status == NodeStatus.SUCCESS
            ]
            for node in succeeded[-5:]:  # last 5 succeeded nodes
                contract = getattr(node, "output_contract", None) or {}
                mime = contract.get("mime_type")
                if mime:
                    for v in self._all:
                        if self._mime_matches(mime, v.spec.condition_type):
                            add_fn(v)
                # typed_artifacts
                for art in (contract.get("typed_artifacts") or []):
                    if isinstance(art, dict):
                        art_mime = art.get("mime_type")
                        if art_mime:
                            for v in self._all:
                                if self._mime_matches(art_mime, v.spec.condition_type):
                                    add_fn(v)
        except Exception as e:
            logger.debug(f"[VerifierRegistry] graph context assembly failed: {e}")

    def get_by_condition_type(
        self, ctype: VerifierConditionType
    ) -> List[BaseVerifier]:
        """Return all verifiers registered for a given condition type."""
        return list(self._by_condition.get(ctype, []))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        from app.avatar.runtime.verification.verifiers.builtin import (
            CsvHasDataVerifier,
            FileExistsVerifier,
            ImageOpenableVerifier,
            JsonParseableVerifier,
            TextContainsVerifier,
        )
        from app.avatar.runtime.verification.verifiers.report_verifier import (
            ReportDeliverableVerifier,
        )
        for cls in [
            FileExistsVerifier,
            JsonParseableVerifier,
            ImageOpenableVerifier,
            CsvHasDataVerifier,
            TextContainsVerifier,
            ReportDeliverableVerifier,
        ]:
            self.register(cls)

    # MIME types that are NOT bitmap images — Pillow cannot open these.
    # They must be excluded from IMAGE_OPENABLE matching.
    _NON_BITMAP_IMAGE_MIMES: frozenset = frozenset({
        "image/svg+xml",
    })

    @staticmethod
    def _mime_matches(mime_type: str, ctype: VerifierConditionType) -> bool:
        """Check if a MIME type implies a particular condition type."""
        _mime_to_ctype: Dict[str, VerifierConditionType] = {
            "application/json": VerifierConditionType.JSON_PARSEABLE,
            "text/csv": VerifierConditionType.CSV_HAS_DATA,
            "image/png": VerifierConditionType.IMAGE_OPENABLE,
            "image/jpeg": VerifierConditionType.IMAGE_OPENABLE,
            "image/gif": VerifierConditionType.IMAGE_OPENABLE,
            "image/bmp": VerifierConditionType.IMAGE_OPENABLE,
            "image/webp": VerifierConditionType.IMAGE_OPENABLE,
        }
        expected = _mime_to_ctype.get(mime_type)
        if expected is None and mime_type.startswith("image/"):
            # SVG etc. are not bitmap — don't route to IMAGE_OPENABLE
            if mime_type not in VerifierRegistry._NON_BITMAP_IMAGE_MIMES:
                expected = VerifierConditionType.IMAGE_OPENABLE
        return expected == ctype
