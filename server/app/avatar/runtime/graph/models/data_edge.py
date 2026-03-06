"""
DataEdge - Typed Data Flow Connection

Represents a typed data flow connection between two nodes.
Replaces string template syntax with explicit field references.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field
import hashlib


def generate_edge_id(source_node: str, target_node: str, target_param: str) -> str:
    """
    Generate deterministic edge ID for easier diff and debugging.
    
    Format: source-target-hash
    where hash is first 8 chars of md5(source_node + target_node + target_param)
    
    Example: s1-s2-a3b4c5d6
    """
    content = f"{source_node}:{target_node}:{target_param}"
    hash_suffix = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{source_node}-{target_node}-{hash_suffix}"


class DataEdge(BaseModel):
    """
    Represents a typed data flow connection between two nodes.
    
    Replaces string template syntax (e.g., {{s1.output}}) with explicit field references.
    This eliminates template parsing errors and enables type validation.
    
    Example:
        # Old way (string template):
        params = {"content": "{{s1.output}}"}
        
        # New way (DataEdge):
        edge = DataEdge(
            source_node="s1",
            source_field="output",
            target_node="s2",
            target_param="content"
        )
    """
    
    id: str = Field(description="Unique edge identifier (deterministic)")
    source_node: str = Field(description="Source node ID")
    source_field: str = Field(description="Field name in source node outputs")
    target_node: str = Field(description="Target node ID")
    target_param: str = Field(description="Parameter name in target node inputs")
    transformer_name: Optional[str] = Field(
        default=None,
        description="Optional transformer to apply (must be pre-registered)"
    )
    optional: bool = Field(
        default=False,
        description="Whether this dependency is optional (for failure propagation)"
    )
    
    def __init__(self, **data):
        # Auto-generate ID if not provided
        if 'id' not in data:
            data['id'] = generate_edge_id(
                data['source_node'],
                data['target_node'],
                data['target_param']
            )
        super().__init__(**data)
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, DataEdge):
            return False
        return self.id == other.id
    
    def to_template_syntax(self) -> str:
        """
        Convert to template syntax for backward compatibility.
        
        Returns:
            String like "{{source_node.source_field}}"
        """
        return f"{{{{{self.source_node}.{self.source_field}}}}}"
    
    @classmethod
    def from_template_syntax(
        cls,
        template: str,
        target_node: str,
        target_param: str
    ) -> 'DataEdge':
        """
        Parse template syntax to create DataEdge.
        
        Args:
            template: Template string like "{{s1.output}}"
            target_node: Target node ID
            target_param: Target parameter name
            
        Returns:
            DataEdge instance
            
        Raises:
            ValueError: If template format is invalid
        """
        import re
        
        # Support both {{}} and ${} syntax
        pattern = r'\{\{(\w+)\.(\w+)\}\}|\$\{(\w+)\.(\w+)\}'
        match = re.match(pattern, template.strip())
        
        if not match:
            raise ValueError(f"Invalid template syntax: {template}")
        
        # Extract source_node and source_field
        if match.group(1):  # {{}} syntax
            source_node = match.group(1)
            source_field = match.group(2)
        else:  # ${} syntax
            source_node = match.group(3)
            source_field = match.group(4)
        
        return cls(
            source_node=source_node,
            source_field=source_field,
            target_node=target_node,
            target_param=target_param
        )
