"""
TransformerRegistry - Registry for Data Transformers

Manages data transformation functions used in DataEdges.
Transformers are pure functions that convert data from one format to another.
"""
from typing import Dict, Callable, Any, List
import json
import re
from threading import Lock


class TransformerRegistry:
    """
    Registry for data transformation functions.
    
    Transformers are used in DataEdges to convert data from source format
    to target format. All transformers must be pure functions with signature:
    (input: Any) -> Any
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize registry with built-in transformers"""
        if self._initialized:
            return
        
        self._transformers: Dict[str, Callable[[Any], Any]] = {}
        self._register_builtin_transformers()
        self._initialized = True
    
    def _register_builtin_transformers(self) -> None:
        """Register all built-in transformers"""
        self.register("split_lines", self._split_lines)
        self.register("json_parse", self._json_parse)
        self.register("extract_field", self._extract_field)
        self.register("regex_extract", self._regex_extract)
        self.register("to_string", self._to_string)
        self.register("to_int", self._to_int)
    
    def register(self, name: str, transformer: Callable[[Any], Any]) -> None:
        """
        Register a transformer function.
        
        Args:
            name: Unique transformer name
            transformer: Callable with signature (input: Any) -> Any
            
        Raises:
            ValueError: If transformer is not callable or name already exists
        """
        if not callable(transformer):
            raise ValueError(f"Transformer '{name}' must be callable")
        
        if name in self._transformers:
            raise ValueError(f"Transformer '{name}' already registered")
        
        self._transformers[name] = transformer
    
    def get(self, name: str) -> Callable[[Any], Any]:
        """
        Get a transformer by name.
        
        Args:
            name: Transformer name
            
        Returns:
            Transformer function
            
        Raises:
            KeyError: If transformer not found
        """
        if name not in self._transformers:
            raise KeyError(f"Transformer '{name}' not found")
        
        return self._transformers[name]
    
    def list_all(self) -> List[str]:
        """
        List all registered transformer names.
        
        Returns:
            List of transformer names
        """
        return list(self._transformers.keys())
    
    def exists(self, name: str) -> bool:
        """Check if transformer exists"""
        return name in self._transformers
    
    # Built-in transformers
    
    @staticmethod
    def _split_lines(input_data: Any) -> List[str]:
        """
        Split text into lines.
        
        Args:
            input_data: Text string
            
        Returns:
            List of lines
        """
        if not isinstance(input_data, str):
            input_data = str(input_data)
        
        return input_data.splitlines()
    
    @staticmethod
    def _json_parse(input_data: Any) -> Any:
        """
        Parse JSON string.
        
        Args:
            input_data: JSON string
            
        Returns:
            Parsed JSON object
            
        Raises:
            json.JSONDecodeError: If input is not valid JSON
        """
        if not isinstance(input_data, str):
            input_data = str(input_data)
        
        return json.loads(input_data)
    
    @staticmethod
    def _extract_field(input_data: Any) -> Callable[[str], Any]:
        """
        Extract field from dict or object.
        
        This is a higher-order transformer that returns a function.
        Usage: extract_field(data)("field_name")
        
        Args:
            input_data: Dict or object
            
        Returns:
            Function that extracts field by name
        """
        def extractor(field_name: str) -> Any:
            if isinstance(input_data, dict):
                if field_name not in input_data:
                    raise ValueError(f"Field '{field_name}' not found in input")
                return input_data[field_name]
            elif hasattr(input_data, field_name):
                return getattr(input_data, field_name)
            else:
                raise ValueError(f"Field '{field_name}' not found in input")
        
        return extractor
    
    @staticmethod
    def _regex_extract(input_data: Any) -> Callable[[str], str]:
        """
        Extract text using regex pattern.
        
        This is a higher-order transformer that returns a function.
        Usage: regex_extract(data)("pattern")
        
        Args:
            input_data: Text string
            
        Returns:
            Function that extracts text matching pattern
        """
        if not isinstance(input_data, str):
            input_data = str(input_data)
        
        def extractor(pattern: str) -> str:
            match = re.search(pattern, input_data)
            if match:
                return match.group(0) if match.lastindex is None else match.group(1)
            else:
                raise ValueError(f"Pattern '{pattern}' not found in input")
        
        return extractor
    
    @staticmethod
    def _to_string(input_data: Any) -> str:
        """
        Convert input to string.
        
        Args:
            input_data: Any value
            
        Returns:
            String representation
        """
        return str(input_data)
    
    @staticmethod
    def _to_int(input_data: Any) -> int:
        """
        Convert input to integer.
        
        Args:
            input_data: Numeric value or string
            
        Returns:
            Integer value
            
        Raises:
            ValueError: If input cannot be converted to int
        """
        if isinstance(input_data, int):
            return input_data
        elif isinstance(input_data, float):
            return int(input_data)
        elif isinstance(input_data, str):
            return int(input_data)
        else:
            raise ValueError(f"Cannot convert {type(input_data)} to int")


# Global registry instance
_registry = TransformerRegistry()


def get_transformer_registry() -> TransformerRegistry:
    """Get the global transformer registry instance"""
    return _registry
