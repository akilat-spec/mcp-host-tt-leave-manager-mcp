from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
import logging

from config import security_config

logger = logging.getLogger(__name__)

class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate API keys for MCP server requests
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip authentication for health checks and root endpoint
        if request.url.path in ["/health", "/", "/docs"]:
            return await call_next(request)
        
        # Skip authentication if disabled
        if not security_config.require_api_key:
            return await call_next(request)
        
        # Extract API key from headers
        api_key = self._extract_api_key(request)
        
        if not api_key:
            logger.warning(f"API key missing for request to {request.url.path}")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "error": "API key required",
                    "message": "Provide x-api-key header or Authorization Bearer token"
                }
            )
        
        # Validate API key
        if not security_config.validate_api_key(api_key):
            logger.warning(f"Invalid API key provided for request to {request.url.path}")
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={
                    "error": "Invalid API key",
                    "message": "The provided API key is not valid"
                }
            )
        
        logger.debug(f"Valid API key used for request to {request.url.path}")
        return await call_next(request)
    
    def _extract_api_key(self, request: Request) -> str:
        """
        Extract API key from request headers
        Supports:
        - x-api-key header
        - Authorization: Bearer <token>
        """
        # Check x-api-key header
        api_key = request.headers.get("x-api-key")
        if api_key:
            return api_key
        
        # Check Authorization header
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        
        return None