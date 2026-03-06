"""
Configuration System for Graph Runtime

This module provides configuration management for the Graph Runtime:
- YAML configuration loading
- Environment-specific profiles (development, staging, production)
- Environment variable overrides
- Configuration validation

Requirements: 24.1, 24.2, 24.7
"""

from __future__ import annotations
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
import yaml
import os
import logging

logger = logging.getLogger(__name__)


@dataclass
class RuntimeConfig:
    """Runtime engine configuration"""
    max_concurrent_graphs: int = 10
    max_nodes_per_graph: int = 200
    max_edges_per_graph: int = 500
    max_execution_time: int = 3600  # seconds
    checkpoint_interval: int = 5  # nodes


@dataclass
class SchedulerConfig:
    """Scheduler configuration"""
    max_concurrent_nodes: int = 10
    priority_enabled: bool = True


@dataclass
class ExecutorConfig:
    """Executor configuration"""
    default_executor: str = "local"
    timeout: int = 300  # seconds
    retry_enabled: bool = True


@dataclass
class PlannerConfig:
    """Planner configuration"""
    default_mode: str = "react"
    max_planner_invocations: int = 200
    max_planner_tokens: int = 100000
    max_planner_cost: float = 10.0  # USD


@dataclass
class ObservabilityConfig:
    """Observability configuration"""
    metrics_enabled: bool = True
    logging_level: str = "INFO"
    tracing_enabled: bool = False
    structured_logging: bool = True


@dataclass
class SecurityConfig:
    """Security configuration"""
    workspace_isolation: bool = True
    max_nodes_per_patch: int = 50
    max_edges_per_patch: int = 100
    approval_required_capabilities: list = field(default_factory=list)
    denied_capabilities: list = field(default_factory=list)


@dataclass
class GraphRuntimeConfig:
    """
    Complete Graph Runtime configuration.
    
    This class holds all configuration for the Graph Runtime system.
    Configuration can be loaded from YAML files and overridden by
    environment variables.
    
    Requirements:
    - 24.1: YAML configuration loading
    - 24.2: Environment-specific profiles
    - 24.7: Environment variable overrides
    """
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    
    @classmethod
    def from_yaml(cls, config_path: str, profile: str = "development") -> 'GraphRuntimeConfig':
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to YAML configuration file
            profile: Environment profile (development, staging, production)
            
        Returns:
            GraphRuntimeConfig instance
            
        Requirements: 24.1, 24.2
        """
        config_file = Path(config_path)
        
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return cls()
        
        try:
            with open(config_file, 'r') as f:
                data = yaml.safe_load(f)
            
            # Get profile-specific config
            if profile in data:
                profile_data = data[profile]
            else:
                logger.warning(f"Profile '{profile}' not found in config, using defaults")
                profile_data = {}
            
            # Create config sections
            runtime = RuntimeConfig(**profile_data.get('runtime', {}))
            scheduler = SchedulerConfig(**profile_data.get('scheduler', {}))
            executor = ExecutorConfig(**profile_data.get('executor', {}))
            planner = PlannerConfig(**profile_data.get('planner', {}))
            observability = ObservabilityConfig(**profile_data.get('observability', {}))
            security = SecurityConfig(**profile_data.get('security', {}))
            
            config = cls(
                runtime=runtime,
                scheduler=scheduler,
                executor=executor,
                planner=planner,
                observability=observability,
                security=security,
            )
            
            # Apply environment variable overrides
            config._apply_env_overrides()
            
            logger.info(f"Loaded configuration from {config_path} (profile: {profile})")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            return cls()
    
    def _apply_env_overrides(self) -> None:
        """
        Apply environment variable overrides.
        
        Environment variables follow the pattern:
        GRAPH_RUNTIME_<SECTION>_<KEY>=value
        
        Example: GRAPH_RUNTIME_PLANNER_MAX_PLANNER_INVOCATIONS=300
        
        Requirements: 24.7
        """
        prefix = "GRAPH_RUNTIME_"
        
        for env_key, env_value in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            
            # Parse env key: GRAPH_RUNTIME_SECTION_KEY
            parts = env_key[len(prefix):].lower().split('_', 1)
            if len(parts) != 2:
                continue
            
            section_name, key_name = parts
            
            # Get section
            if not hasattr(self, section_name):
                continue
            
            section = getattr(self, section_name)
            
            # Set value
            if hasattr(section, key_name):
                # Convert value to appropriate type
                current_value = getattr(section, key_name)
                if isinstance(current_value, bool):
                    new_value = env_value.lower() in ('true', '1', 'yes')
                elif isinstance(current_value, int):
                    new_value = int(env_value)
                elif isinstance(current_value, float):
                    new_value = float(env_value)
                elif isinstance(current_value, list):
                    new_value = env_value.split(',')
                else:
                    new_value = env_value
                
                setattr(section, key_name, new_value)
                logger.debug(f"Applied env override: {section_name}.{key_name} = {new_value}")
    
    @classmethod
    def default(cls) -> 'GraphRuntimeConfig':
        """
        Create default configuration.
        
        Returns:
            GraphRuntimeConfig with default values
        """
        return cls()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration
        """
        return {
            'runtime': self.runtime.__dict__,
            'scheduler': self.scheduler.__dict__,
            'executor': self.executor.__dict__,
            'planner': self.planner.__dict__,
            'observability': self.observability.__dict__,
            'security': self.security.__dict__,
        }
