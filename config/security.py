import os
from typing import List

class SecurityConfig:
    """Security configuration for API key authentication"""
    
    def __init__(self):
        self.api_keys = self._load_api_keys()
        self.require_api_key = os.environ.get("REQUIRE_API_KEY", "True").lower() == "true"
    
    def _load_api_keys(self) -> List[str]:
        """Load and validate API keys from environment"""
        api_keys_str = os.environ.get("MCP_API_KEYS", "")
        if not api_keys_str:
            return []
        
        keys = [key.strip() for key in api_keys_str.split(",") if key.strip()]
        return keys
    
    def validate_api_key(self, api_key: str) -> bool:
        """Validate the provided API key"""
        if not self.require_api_key:
            return True
        
        if not api_key:
            return False
        
        return api_key in self.api_keys
    
    @property
    def is_authentication_enabled(self) -> bool:
        """Check if authentication is enabled and configured"""
        return self.require_api_key and len(self.api_keys) > 0

# Global security configuration instance
security_config = SecurityConfig()