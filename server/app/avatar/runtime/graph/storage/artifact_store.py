"""
ArtifactStore: Large Artifact Management System

This module provides storage, retrieval, and lifecycle management for large files and data artifacts
produced during graph execution. Supports multiple storage backends (local filesystem, S3/MinIO)
with size limits, TTL-based garbage collection, and streaming for large files.

Requirements: 30.1-30.14
"""

from __future__ import annotations
from typing import Any, Dict, Optional, AsyncIterator, TYPE_CHECKING
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import hashlib
import logging
import asyncio
from pydantic import BaseModel, Field

# Async file I/O
try:
    import aiofiles
except ImportError:
    aiofiles = None

# S3/MinIO support
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception

if TYPE_CHECKING:
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


# ==========================================
# Exceptions
# ==========================================

class ArtifactSizeExceeded(Exception):
    """Raised when artifact size exceeds limits."""
    pass


class ArtifactNotFound(Exception):
    """Raised when artifact is not found."""
    pass


# ==========================================
# Data Models
# ==========================================

class ArtifactType(str, Enum):
    """
    Supported artifact types.
    
    Requirements: 30.2
    """
    FILE = "file"
    DATASET = "dataset"
    IMAGE = "image"
    LOG = "log"
    EMBEDDING = "embedding"
    MODEL = "model"
    ARCHIVE = "archive"


class Artifact(BaseModel):
    """
    Metadata for a stored artifact.
    
    Requirements:
    - 30.1: Contains id, type, uri, size, metadata, created_by_node, created_at
    - 30.14: Includes content_type, encoding, checksum for integrity
    """
    id: str = Field(description="Unique artifact identifier")
    type: ArtifactType = Field(description="Artifact type")
    uri: str = Field(description="Storage URI (backend-specific)")
    size: int = Field(description="Size in bytes")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_by_node: str = Field(description="Node that created this artifact")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    ttl_days: Optional[int] = Field(default=30, description="Time-to-live in days")
    content_type: Optional[str] = Field(default=None, description="MIME type")
    encoding: Optional[str] = Field(default=None, description="Character encoding")
    checksum: Optional[str] = Field(default=None, description="SHA-256 checksum for integrity")
    
    def is_expired(self) -> bool:
        """
        Check if artifact has exceeded its TTL.
        
        Returns:
            True if expired, False otherwise
            
        Requirements: 30.12
        """
        if self.ttl_days is None:
            return False
        expiry_date = self.created_at + timedelta(days=self.ttl_days)
        return datetime.utcnow() > expiry_date


# ==========================================
# Storage Backend Interface
# ==========================================

class IStorageBackend(ABC):
    """
    Abstract interface for storage backends.
    
    Implementations must support: local filesystem, S3, MinIO, Azure Blob Storage
    
    Requirements: 30.6
    """
    
    @abstractmethod
    async def store(self, artifact_id: str, data: bytes, metadata: Dict[str, Any]) -> str:
        """
        Store artifact data and return storage URI.
        
        Args:
            artifact_id: Unique artifact identifier
            data: Artifact data as bytes
            metadata: Additional metadata (includes graph_id)
            
        Returns:
            Storage URI for retrieval
            
        Requirements: 30.3, 30.7, 30.8, 30.9
        """
        pass
    
    @abstractmethod
    async def retrieve(self, uri: str) -> bytes:
        """
        Retrieve complete artifact data.
        
        Args:
            uri: Storage URI
            
        Returns:
            Artifact data as bytes
            
        Requirements: 30.3
        """
        pass
    
    @abstractmethod
    async def stream_retrieve(self, uri: str) -> AsyncIterator[bytes]:
        """
        Stream artifact data in chunks (for large files).
        
        Args:
            uri: Storage URI
            
        Yields:
            Chunks of artifact data
            
        Requirements: 30.13
        """
        pass
    
    @abstractmethod
    async def delete(self, uri: str) -> bool:
        """
        Delete artifact from storage.
        
        Args:
            uri: Storage URI
            
        Returns:
            True if deleted successfully, False otherwise
            
        Requirements: 30.3
        """
        pass
    
    @abstractmethod
    async def exists(self, uri: str) -> bool:
        """
        Check if artifact exists in storage.
        
        Args:
            uri: Storage URI
            
        Returns:
            True if exists, False otherwise
        """
        pass


# ==========================================
# Local Filesystem Backend
# ==========================================

class LocalStorageBackend(IStorageBackend):
    """
    Local filesystem storage backend.
    
    Stores artifacts in: {base_path}/{graph_id}/{artifact_id}
    
    Requirements: 30.6, 30.8
    """
    
    def __init__(self, base_path: str):
        """
        Initialize local storage backend.
        
        Args:
            base_path: Base directory for artifact storage
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[LocalStorageBackend] Initialized with base_path: {self.base_path}")
    
    async def store(self, artifact_id: str, data: bytes, metadata: Dict[str, Any]) -> str:
        """
        Store artifact in local filesystem.
        
        Requirements: 30.8
        """
        graph_id = metadata.get('graph_id', 'default')
        artifact_dir = self.base_path / graph_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = artifact_dir / artifact_id
        
        if aiofiles:
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(data)
        else:
            # Fallback to synchronous I/O
            with open(file_path, 'wb') as f:
                f.write(data)
        
        logger.debug(f"[LocalStorageBackend] Stored artifact {artifact_id} at {file_path}")
        return str(file_path)
    
    async def retrieve(self, uri: str) -> bytes:
        """Retrieve artifact from local filesystem."""
        if aiofiles:
            async with aiofiles.open(uri, 'rb') as f:
                return await f.read()
        else:
            with open(uri, 'rb') as f:
                return f.read()
    
    async def stream_retrieve(self, uri: str) -> AsyncIterator[bytes]:
        """Stream artifact from local filesystem in 8KB chunks."""
        if aiofiles:
            async with aiofiles.open(uri, 'rb') as f:
                while chunk := await f.read(8192):
                    yield chunk
        else:
            with open(uri, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
    
    async def delete(self, uri: str) -> bool:
        """Delete artifact from local filesystem."""
        try:
            Path(uri).unlink()
            logger.debug(f"[LocalStorageBackend] Deleted artifact at {uri}")
            return True
        except Exception as e:
            logger.error(f"[LocalStorageBackend] Failed to delete {uri}: {e}")
            return False
    
    async def exists(self, uri: str) -> bool:
        """Check if artifact exists in local filesystem."""
        return Path(uri).exists()


# ==========================================
# S3/MinIO Backend
# ==========================================

class S3StorageBackend(IStorageBackend):
    """
    S3-compatible storage backend (supports AWS S3, MinIO, etc.).
    
    Stores artifacts with path: artifacts/{graph_id}/{artifact_id}
    
    Requirements: 30.6, 30.9
    """
    
    def __init__(
        self,
        bucket: str,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = 'us-east-1'
    ):
        """
        Initialize S3 storage backend.
        
        Args:
            bucket: S3 bucket name
            endpoint: Optional endpoint URL (for MinIO or custom S3)
            access_key: AWS access key ID
            secret_key: AWS secret access key
            region: AWS region
        """
        if boto3 is None:
            raise ImportError("boto3 is required for S3StorageBackend. Install with: pip install boto3")
        
        self.bucket = bucket
        self.endpoint = endpoint
        
        # Initialize S3 client
        client_kwargs = {
            'region_name': region
        }
        
        if endpoint:
            client_kwargs['endpoint_url'] = endpoint
        
        if access_key and secret_key:
            client_kwargs['aws_access_key_id'] = access_key
            client_kwargs['aws_secret_access_key'] = secret_key
        
        self.s3_client = boto3.client('s3', **client_kwargs)
        
        logger.info(f"[S3StorageBackend] Initialized with bucket: {bucket}, endpoint: {endpoint}")
    
    async def store(self, artifact_id: str, data: bytes, metadata: Dict[str, Any]) -> str:
        """
        Store artifact in S3.
        
        Requirements: 30.9
        """
        graph_id = metadata.get('graph_id', 'default')
        key = f"artifacts/{graph_id}/{artifact_id}"
        
        try:
            # Convert metadata to string values for S3
            s3_metadata = {k: str(v) for k, v in metadata.items()}
            
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                Metadata=s3_metadata
            )
            
            uri = f"s3://{self.bucket}/{key}"
            logger.debug(f"[S3StorageBackend] Stored artifact {artifact_id} at {uri}")
            return uri
            
        except ClientError as e:
            logger.error(f"[S3StorageBackend] Failed to store artifact {artifact_id}: {e}")
            raise
    
    async def retrieve(self, uri: str) -> bytes:
        """Retrieve artifact from S3."""
        bucket, key = self._parse_uri(uri)
        
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            return response['Body'].read()
        except ClientError as e:
            logger.error(f"[S3StorageBackend] Failed to retrieve {uri}: {e}")
            raise ArtifactNotFound(f"Artifact not found: {uri}")
    
    async def stream_retrieve(self, uri: str) -> AsyncIterator[bytes]:
        """Stream artifact from S3 in chunks."""
        bucket, key = self._parse_uri(uri)
        
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            for chunk in response['Body'].iter_chunks(chunk_size=8192):
                yield chunk
        except ClientError as e:
            logger.error(f"[S3StorageBackend] Failed to stream {uri}: {e}")
            raise ArtifactNotFound(f"Artifact not found: {uri}")
    
    async def delete(self, uri: str) -> bool:
        """Delete artifact from S3."""
        bucket, key = self._parse_uri(uri)
        
        try:
            self.s3_client.delete_object(Bucket=bucket, Key=key)
            logger.debug(f"[S3StorageBackend] Deleted artifact at {uri}")
            return True
        except ClientError as e:
            logger.error(f"[S3StorageBackend] Failed to delete {uri}: {e}")
            return False
    
    async def exists(self, uri: str) -> bool:
        """Check if artifact exists in S3."""
        bucket, key = self._parse_uri(uri)
        
        try:
            self.s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False
    
    def _parse_uri(self, uri: str) -> tuple[str, str]:
        """
        Parse S3 URI into bucket and key.
        
        Args:
            uri: S3 URI (s3://bucket/key)
            
        Returns:
            Tuple of (bucket, key)
        """
        if not uri.startswith('s3://'):
            raise ValueError(f"Invalid S3 URI: {uri}")
        
        parts = uri.replace('s3://', '').split('/', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid S3 URI format: {uri}")
        
        return parts[0], parts[1]


# ==========================================
# ArtifactStore
# ==========================================

class ArtifactStore:
    """
    Manages large file and data artifacts with lifecycle management.
    
    Features:
    - Multiple storage backends (local, S3/MinIO)
    - Size limit enforcement
    - TTL-based garbage collection
    - Streaming support for large files
    - Integrity verification with checksums
    
    Requirements: 30.1-30.14
    """
    
    def __init__(
        self,
        backend: IStorageBackend,
        execution_context: Optional['ExecutionContext'] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        self.backend = backend
        self.execution_context = execution_context
        config = config or {}
        
        # Size limits (Requirements 30.10, 30.11)
        self.max_artifact_size = config.get('max_artifact_size', 1 * 1024 * 1024 * 1024)  # 1GB
        self.max_total_size = config.get('max_total_artifacts_size', 10 * 1024 * 1024 * 1024)  # 10GB
        
        # Lifecycle settings (Requirements 30.13, 30.14)
        self.artifact_ttl_days = config.get('artifact_ttl_days', 30)
        self.gc_interval_hours = config.get('artifact_gc_interval', 24)
        
        # In-memory artifact registry
        self._artifacts: Dict[str, Artifact] = {}
        self._total_size: int = 0
        
        logger.info(
            f"[ArtifactStore] Initialized with backend={type(backend).__name__}, "
            f"max_size={self.max_artifact_size}, ttl={self.artifact_ttl_days}d"
        )
    
    async def store(
        self,
        data: bytes,
        artifact_type: ArtifactType,
        created_by_node: str,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_days: Optional[int] = None
    ) -> Artifact:
        """
        Store artifact data and return Artifact model.
        
        Requirements: 30.1, 30.2, 30.6, 30.10
        """
        # Check size limit (Requirement 30.10)
        if len(data) > self.max_artifact_size:
            raise ArtifactSizeExceeded(
                f"Artifact size {len(data)} exceeds limit {self.max_artifact_size}"
            )
        
        # Check total size limit (Requirement 30.11)
        if self._total_size + len(data) > self.max_total_size:
            raise ArtifactSizeExceeded(
                f"Total artifact size would exceed limit {self.max_total_size}"
            )
        
        artifact_id = str(uuid.uuid4())
        checksum = hashlib.sha256(data).hexdigest()
        
        artifact_metadata = {
            "checksum": checksum,
            "artifact_type": artifact_type.value,
            "created_by_node": created_by_node,
            **(metadata or {})
        }
        
        # Store via backend
        uri = await self.backend.store(artifact_id, data, artifact_metadata)
        
        # Create artifact record
        artifact = Artifact(
            id=artifact_id,
            type=artifact_type,
            uri=uri,
            size=len(data),
            metadata=artifact_metadata,
            created_by_node=created_by_node,
            ttl_days=ttl_days or self.artifact_ttl_days
        )
        
        self._artifacts[artifact_id] = artifact
        self._total_size += len(data)
        
        # Track in ExecutionContext if available (Requirement 29.3)
        if self.execution_context:
            self.execution_context.set_artifact(artifact_id, artifact.model_dump())
        
        logger.info(
            f"[ArtifactStore] Stored artifact {artifact_id} "
            f"(type={artifact_type.value}, size={len(data)}, node={created_by_node})"
        )
        
        return artifact
    
    async def retrieve(self, artifact_id: str) -> bytes:
        """
        Retrieve artifact data by ID.
        
        Requirements: 30.3
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ArtifactNotFound(f"Artifact {artifact_id} not found")
        
        data = await self.backend.retrieve(artifact.uri)
        
        # Verify checksum
        checksum = hashlib.sha256(data).hexdigest()
        stored_checksum = artifact.metadata.get("checksum")
        if stored_checksum and checksum != stored_checksum:
            raise ValueError(f"Artifact {artifact_id} checksum mismatch")
        
        return data
    
    async def stream_retrieve(self, artifact_id: str) -> AsyncIterator[bytes]:
        """
        Stream artifact data for large files.
        
        Requirements: 30.7
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ArtifactNotFound(f"Artifact {artifact_id} not found")
        
        async for chunk in self.backend.stream_retrieve(artifact.uri):
            yield chunk
    
    async def delete(self, artifact_id: str) -> bool:
        """
        Delete artifact by ID.
        
        Requirements: 30.8
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return False
        
        success = await self.backend.delete(artifact.uri)
        if success:
            self._total_size -= artifact.size
            del self._artifacts[artifact_id]
            logger.info(f"[ArtifactStore] Deleted artifact {artifact_id}")
        
        return success
    
    async def gc(self) -> int:
        """
        Garbage collect expired artifacts.
        
        Requirements: 30.13, 30.14
        """
        expired = [a for a in self._artifacts.values() if a.is_expired()]
        count = 0
        
        for artifact in expired:
            if await self.delete(artifact.id):
                count += 1
        
        if count:
            logger.info(f"[ArtifactStore] GC removed {count} expired artifacts")
        
        return count
    
    def get_artifact_info(self, artifact_id: str) -> Optional[Artifact]:
        """Get artifact metadata without retrieving data."""
        return self._artifacts.get(artifact_id)
    
    def list_artifacts(self, created_by_node: Optional[str] = None) -> List[Artifact]:
        """List all artifacts, optionally filtered by node."""
        artifacts = list(self._artifacts.values())
        if created_by_node:
            artifacts = [a for a in artifacts if a.created_by_node == created_by_node]
        return artifacts
    
    @property
    def total_size(self) -> int:
        """Total size of all stored artifacts."""
        return self._total_size
