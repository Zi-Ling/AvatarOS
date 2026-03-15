"""
DomainPacks — scenario-specific verification and prompt bundles.

Built-in packs:
  - file_batch_processing
  - report_generation
  - repo_analysis
"""
from app.avatar.runtime.verification.domain_packs.domain_pack import DomainPack
from app.avatar.runtime.verification.domain_packs.builtin import BUILTIN_DOMAIN_PACKS

__all__ = ["DomainPack", "BUILTIN_DOMAIN_PACKS"]
