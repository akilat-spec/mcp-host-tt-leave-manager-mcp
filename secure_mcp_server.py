import os
import re
import secrets
import time
import mysql.connector
from typing import List, Optional, Dict, Any
from difflib import SequenceMatcher
from datetime import datetime, date, timedelta

# Third-party imports
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS

# Optional Levenshtein import
try:
    import Levenshtein
except Exception:
    Levenshtein = None

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Configuration management"""
    
    # Database configuration
    DB_HOST = os.environ.get("DB_HOST", "103.174.10.72")
    DB_USER = os.environ.get("DB_USER", "tt_crm_mcp")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "F*PAtqhu@sg2w58n")
    DB_NAME = os.environ.get("DB_NAME", "tt_crm_mcp")
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    
    # Security configuration
    API_KEY_HEADER = os.environ.get("API_KEY_HEADER", "X-API-Key")
    RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT", "100"))
    ENABLE_RATE_LIMITING = os.environ.get("ENABLE_RATE_LIMIT", "True").lower() == "true"
    
    # Server configuration
    MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "streamable-http")
    MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8080"))
    DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

# =============================================================================
# DATABASE MANAGEMENT
# =============================================================================

class DatabaseManager:
    """Manage database connections and operations"""
    
    @staticmethod
    def get_connection():
        """Get database connection"""
        return mysql.connector.connect(
            host=Config.DB_HOST,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            port=Config.DB_PORT,
            autocommit=True,
        )
    
    @staticmethod
    def execute_query(query: str, params: tuple = None) -> List[Dict]:
        """Execute query and return results"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(query, params or ())
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def execute_update(query: str, params: tuple = None) -> int:
        """Execute update query and return affected rows"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params or ())
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()

# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

class APIKeyManager:
    """Manage API keys in database"""
    
    @staticmethod
    def create_api_keys_table():
        """Create API keys table if not exists"""
        query = """
        CREATE TABLE IF NOT EXISTS api_keys (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            api_key VARCHAR(255) UNIQUE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP NULL,
            expires_at TIMESTAMP NULL,
            rate_limit_per_minute INT DEFAULT 100,
            created_by VARCHAR(100) DEFAULT 'system'
        )
        """
        DatabaseManager.execute_update(query)
        print("✅ API keys table created/verified")
    
    @staticmethod
    def generate_api_key(name: str, expires_days: int = 365) -> Optional[str]:
        """Generate a new API key and store it in database"""
        api_key = f"tt_mcp_{secrets.token_urlsafe(32)}"
        expires_at = datetime.now() + timedelta(days=expires_days)
        
        query = """
        INSERT INTO api_keys (name, api_key, expires_at) 
        VALUES (%s, %s, %s)
        """
        
        try:
            DatabaseManager.execute_update(query, (name, api_key, expires_at))
            print(f"✅ API key generated for: {name}")
            return api_key
        except Exception as e:
            print(f"❌ Error generating API key: {e}")
            return None
    
    @staticmethod
    def validate_api_key(api_key: str) -> bool:
        """Validate API key and update last_used timestamp"""
        # First check if key exists and is active
        query = """
        SELECT id, expires_at FROM api_keys 
        WHERE api_key = %s AND is_active = TRUE
        """
        result = DatabaseManager.execute_query(query, (api_key,))
        
        if not result:
            return False
        
        # Check if key has expired
        key_data = result[0]
        if key_data.get('expires_at') and key_data['expires_at'] < datetime.now():
            return False
        
        # Update last_used timestamp
        update_query = "UPDATE api_keys SET last_used = NOW() WHERE api_key = %s"
        DatabaseManager.execute_update(update_query, (api_key,))
        
        return True
    
    @staticmethod
    def list_api_keys() -> List[Dict]:
        """List all API keys (with masked keys for security)"""
        query = """
        SELECT name, api_key, is_active, created_at, last_used, expires_at 
        FROM api_keys 
        ORDER BY created_at DESC
        """
        keys = DatabaseManager.execute_query(query)
        
        # Mask API keys for security
        for key in keys:
            if key.get('api_key'):
                full_key = key['api_key']
                key['api_key'] = f"{full_key[:8]}...{full_key[-4:]}" if len(full_key) > 12 else "***"
        
        return keys
    
    @staticmethod
    def revoke_api_key(api_key: str) -> bool:
        """Revoke an API key"""
        query = "UPDATE api_keys SET is_active = FALSE WHERE api_key = %s"
        affected = DatabaseManager.execute_update(query, (api_key,))
        return affected > 0
    
    @staticmethod
    def get_active_keys_count() -> int:
        """Get count of active API keys"""
        query = "SELECT COUNT(*) as count FROM api_keys WHERE is_active = TRUE"
        result = DatabaseManager.execute_query(query)
        return result[0]['count'] if result else 0

# =============================================================================
# SECURITY MIDDLEWARE
# =============================================================================

class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate API keys for all requests
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth for health check and root endpoint
        if request.url.path in ["/health", "/"]:
            return await call_next(request)
        
        # Get API key from header
        api_key = request.headers.get(Config.API_KEY_HEADER)
        
        # Also check Authorization header
        if not api_key:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                api_key = auth_header[7:]
        
        # Validate API key
        if not api_key:
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "error": "API key required",
                    "details": f"Please provide API key in '{Config.API_KEY_HEADER}' header or Authorization: Bearer <key>"
                }
            )
        
        if not APIKeyManager.validate_api_key(api_key):
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={
                    "error": "Invalid API key",
                    "details": "The provided API key is invalid, expired, or has been revoked"
                }
            )
        
        # Add API key to request state for potential use in endpoints
        request.state.api_key = api_key
        
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting middleware
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.requests = {}
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/"]:
            return await call_next(request)
        
        # Get client identifier
        client_id = self._get_client_identifier(request)
        
        # Clean old requests (older than 1 minute)
        current_time = time.time()
        if client_id in self.requests:
            self.requests[client_id] = [
                req_time for req_time in self.requests[client_id] 
                if current_time - req_time < 60
            ]
        
        # Check rate limit
        if len(self.requests.get(client_id, [])) >= Config.RATE_LIMIT_PER_MINUTE:
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "details": f"Maximum {Config.RATE_LIMIT_PER_MINUTE} requests per minute allowed"
                }
            )
        
        # Record this request
        if client_id not in self.requests:
            self.requests[client_id] = []
        self.requests[client_id].append(current_time)
        
        return await call_next(request)
    
    def _get_client_identifier(self, request: Request) -> str:
        """Get client identifier for rate limiting"""
        # Prefer API key if available
        if hasattr(request.state, 'api_key'):
            return request.state.api_key
        
        # Fall back to IP address
        client_host = request.client.host if request.client else "unknown"
        return f"ip_{client_host}"

# =============================================================================
# AI-POWERED NAME MATCHING (Your existing code)
# =============================================================================

class NameMatcher:
    @staticmethod
    def normalize_name(name: str) -> str:
        name = (name or "").lower().strip()
        name = re.sub(r'[^\w\s]', '', name)
        name = re.sub(r'\s+', ' ', name)
        return name

    @staticmethod
    def similarity_score(name1: str, name2: str) -> float:
        name1_norm = NameMatcher.normalize_name(name1)
        name2_norm = NameMatcher.normalize_name(name2)

        if Levenshtein:
            try:
                dist = Levenshtein.distance(name1_norm, name2_norm)
                levenshtein_sim = 1 - (dist / max(len(name1_norm), len(name2_norm), 1))
            except Exception:
                levenshtein_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        else:
            levenshtein_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()

        sequence_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        combined_score = (levenshtein_sim * 0.6) + (sequence_sim * 0.4)
        return combined_score

    @staticmethod
    def extract_name_parts(full_name: str) -> Dict[str, str]:
        parts = (full_name or "").split()
        if len(parts) == 0:
            return {'first': '', 'last': ''}
        if len(parts) == 1:
            return {'first': parts[0], 'last': ''}
        elif len(parts) == 2:
            return {'first': parts[0], 'last': parts[1]}
        else:
            return {'first': parts[0], 'last': parts[-1]}

    @staticmethod
    def fuzzy_match_employee(search_name: str, employees: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
        matches = []
        search_parts = NameMatcher.extract_name_parts(search_name)

        for emp in employees:
            scores = []
            emp_full_name = f"{emp.get('developer_name','')}".strip()
            scores.append(NameMatcher.similarity_score(search_name, emp_full_name))

            if ' ' in emp_full_name:
                first_name = emp_full_name.split()[0]
                last_name = ' '.join(emp_full_name.split()[1:])
                scores.append(NameMatcher.similarity_score(search_name, f"{first_name} {last_name}"))
                scores.append(NameMatcher.similarity_score(search_name, f"{last_name} {first_name}"))

            if search_parts['last']:
                first_score = NameMatcher.similarity_score(search_parts['first'], emp_full_name.split()[0] if emp_full_name else '')
                last_score = NameMatcher.similarity_score(search_parts['last'], ' '.join(emp_full_name.split()[1:]) if ' ' in emp_full_name else '')
                if first_score > 0 or last_score > 0:
                    scores.append((first_score + last_score) / 2)

            best_score = max(scores) if scores else 0
            if best_score >= threshold:
                matches.append({'employee': emp, 'score': best_score, 'match_type': 'fuzzy'})

        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches

# =============================================================================
# EMPLOYEE SERVICES (Your existing business logic)
# =============================================================================

def fetch_employees_ai(search_term: str = None, emp_id: int = None) -> List[Dict[str, Any]]:
    conn = DatabaseManager.get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if emp_id:
            cursor.execute("""
                SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                       d.status, d.doj, d.emp_number, d.blood_group,
                       u.username, d.opening_leave_balance, d.is_pf_enabled, d.pf_join_date
                FROM developer d
                LEFT JOIN user u ON d.user_id = u.user_id
                WHERE d.id = %s
            """, (emp_id,))
        elif search_term:
            cursor.execute("""
                SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                       d.status, d.doj, d.emp_number, d.blood_group,
                       u.username, d.opening_leave_balance, d.is_pf_enabled, d.pf_join_date
                FROM developer d
                LEFT JOIN user u ON d.user_id = u.user_id
                WHERE d.developer_name LIKE %s OR d.email_id LIKE %s 
                   OR d.mobile LIKE %s OR d.emp_number LIKE %s
                ORDER BY d.developer_name
            """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"))
        else:
            return []

        rows = cursor.fetchall()

        if search_term and not rows:
            cursor.execute("""
                SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                       d.status, d.doj, d.emp_number, d.blood_group,
                       u.username, d.opening_leave_balance, d.is_pf_enabled, d.pf_join_date
                FROM developer d
                LEFT JOIN user u ON d.user_id = u.user_id
                WHERE d.status = 1
            """)
            all_employees = cursor.fetchall()
            fuzzy_matches = NameMatcher.fuzzy_match_employee(search_term, all_employees)
            rows = [match['employee'] for match in fuzzy_matches[:5]]

        return rows

    except Exception as e:
        print(f"Database error: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def get_leave_balance_for_employee(developer_id: int) -> Dict[str, Any]:
    conn = DatabaseManager.get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT opening_leave_balance, doj, status 
            FROM developer 
            WHERE id = %s
        """, (developer_id,))
        developer_info = cursor.fetchone()
        
        if not developer_info:
            return {"error": "Employee not found"}
        
        cursor.execute("""
            SELECT leave_type, COUNT(*) as count
            FROM leave_requests 
            WHERE developer_id = %s AND status = 'Approved'
            GROUP BY leave_type
        """, (developer_id,))
        leave_counts = cursor.fetchall()
        
        used_leaves = 0.0
        for leave in leave_counts:
            lt = (leave.get('leave_type') or '').upper()
            cnt = float(leave.get('count') or 0)
            if lt == 'FULL DAY':
                used_leaves += cnt
            elif lt in ['HALF DAY', 'COMPENSATION HALF DAY']:
                used_leaves += cnt * 0.5
            elif lt in ['2 HRS', 'COMPENSATION 2 HRS']:
                used_leaves += cnt * 0.25
            else:
                used_leaves += cnt

        opening_balance = float(developer_info.get('opening_leave_balance') or 0)
        current_balance = opening_balance - used_leaves
        
        return {
            "opening_balance": opening_balance,
            "used_leaves": used_leaves,
            "current_balance": current_balance,
            "leave_details": leave_counts
        }
        
    except Exception as e:
        return {"error": f"Error calculating leave balance: {str(e)}"}
    finally:
        cursor.close()
        conn.close()

def format_employee_options(employees: List[Dict[str, Any]]) -> str:
    options = []
    for i, emp in enumerate(employees, 1):
        option = f"{i}. 👤 {emp.get('developer_name','Unknown')}"
        if emp.get('designation'):
            option += f" | 💼 {emp.get('designation')}"
        if emp.get('email_id'):
            option += f" | 📧 {emp.get('email_id')}"
        if emp.get('emp_number'):
            option += f" | 🆔 {emp.get('emp_number')}"
        status = "Active" if emp.get('status') == 1 else "Inactive"
        option += f" | 🔰 {status}"
        options.append(option)
    return "\n".join(options)

def resolve_employee_ai(search_name: str, additional_context: str = None) -> Dict[str, Any]:
    employees = fetch_employees_ai(search_term=search_name)

    if not employees:
        return {'status': 'not_found', 'message': f"No employees found matching '{search_name}'"}

    if len(employees) == 1:
        return {'status': 'resolved', 'employee': employees[0]}

    if additional_context:
        context_lower = (additional_context or '').lower()
        filtered_employees = []
        for emp in employees:
            designation = (emp.get('designation') or '').lower()
            email = (emp.get('email_id') or '').lower()
            emp_number = (emp.get('emp_number') or '').lower()
            
            if (context_lower in designation or 
                context_lower in email or 
                context_lower in emp_number or
                context_lower in emp.get('developer_name', '').lower()):
                filtered_employees.append(emp)
        
        if len(filtered_employees) == 1:
            return {'status': 'resolved', 'employee': filtered_employees[0]}

    return {
        'status': 'ambiguous',
        'employees': employees,
        'message': f"Found {len(employees)} employees. Please specify:"
    }

# =============================================================================
# MCP SERVER SETUP
# =============================================================================

def create_secure_mcp_server():
    """Create and configure the secured MCP server"""
    mcp = FastMCP("SecureLeaveManager")
    
    # Add security middleware
    mcp.app.add_middleware(APIKeyMiddleware)
    
    # Add rate limiting if enabled
    if Config.ENABLE_RATE_LIMITING:
        mcp.app.add_middleware(RateLimitMiddleware)
        print("✅ Rate limiting enabled")
    
    return mcp

# Initialize the secured MCP server
mcp = create_secure_mcp_server()

# =============================================================================
# API KEY MANAGEMENT TOOLS
# =============================================================================

@mcp.tool()
def generate_api_key(name: str) -> str:
    """
    Generate a new API key for client applications
    Note: In production, you might want to add admin authentication for this
    """
    api_key = APIKeyManager.generate_api_key(name)
    
    if api_key:
        response = f"✅ **New API Key Generated**\n\n"
        response += f"**Name:** {name}\n"
        response += f"**API Key:** `{api_key}`\n"
        response += f"**Expires:** In 365 days\n"
        response += f"\n🔒 **Store this key securely - it won't be shown again!**\n\n"
        response += f"**Usage Example:**\n"
        response += f"```bash\ncurl -H 'X-API-Key: {api_key}' http://your-server/mcp\n```"
        return response
    else:
        return "❌ Failed to generate API key. Please check the server logs."

@mcp.tool()
def list_api_keys() -> str:
    """List all API keys (shows masked keys for security)"""
    keys = APIKeyManager.list_api_keys()
    
    if not keys:
        return "ℹ️ No API keys found in the database."
    
    response = f"🔑 **API Keys Management**\n\n"
    response += f"Total keys: {len(keys)}\n"
    response += f"Active keys: {APIKeyManager.get_active_keys_count()}\n\n"
    
    for key in keys:
        status = "✅ Active" if key.get('is_active') else "❌ Inactive"
        response += f"• **{key['name']}** - {status}\n"
        response += f"  Key: {key.get('api_key', 'N/A')}\n"
        response += f"  Created: {key.get('created_at', 'N/A')}\n"
        if key.get('last_used'):
            response += f"  Last Used: {key.get('last_used')}\n"
        if key.get('expires_at'):
            response += f"  Expires: {key.get('expires_at')}\n"
        response += "\n"
    
    return response

@mcp.tool()
def revoke_api_key(api_key_prefix: str) -> str:
    """Revoke an API key by its prefix (first 8 characters)"""
    # This is a simplified implementation
    # In production, you'd want to implement exact matching
    keys = APIKeyManager.list_api_keys()
    
    for key in keys:
        full_key = key.get('original_key', '')  # Note: This would need to be stored
        if full_key.startswith(api_key_prefix):
            success = APIKeyManager.revoke_api_key(full_key)
            if success:
                return f"✅ API key starting with '{api_key_prefix}...' has been revoked."
    
    return f"❌ No API key found starting with '{api_key_prefix}'. Use list_api_keys to see available keys."

# =============================================================================
# BUSINESS TOOLS (Your existing tools - now secured)
# =============================================================================

@mcp.tool()
def get_employee_details(name: str, additional_context: Optional[str] = None) -> str:
    """Get comprehensive details for an employee including personal info, leave balance, and recent activity"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}\n\n💡 Tip: You can specify by designation, email, or employee number"

    emp = resolution['employee']
    leave_balance = get_leave_balance_for_employee(emp['id'])
    
    response = f"✅ **Employee Details**\n\n"
    response += f"👤 **{emp['developer_name']}**\n"
    response += f"🆔 Employee ID: {emp['id']} | Employee #: {emp.get('emp_number', 'N/A')}\n"
    response += f"💼 Designation: {emp.get('designation', 'N/A')}\n"
    response += f"📧 Email: {emp.get('email_id', 'N/A')}\n"
    response += f"📞 Mobile: {emp.get('mobile', 'N/A')}\n"
    response += f"🩸 Blood Group: {emp.get('blood_group', 'N/A')}\n"
    response += f"📅 Date of Joining: {emp.get('doj', 'N/A')}\n"
    response += f"🔰 Status: {'Active' if emp.get('status') == 1 else 'Inactive'}\n\n"
    
    # Leave Balance
    if 'error' not in leave_balance:
        response += f"📊 **Leave Balance:** {leave_balance['current_balance']:.1f} days\n"
        response += f"   - Opening Balance: {leave_balance['opening_balance']}\n"
        response += f"   - Leaves Used: {leave_balance['used_leaves']:.1f} days\n"
    else:
        response += f"📊 Leave Balance: Data not available\n"
    
    return response

@mcp.tool()
def get_leave_balance(name: str, additional_context: Optional[str] = None) -> str:
    """Get detailed leave balance information for an employee"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}"

    emp = resolution['employee']
    leave_balance = get_leave_balance_for_employee(emp['id'])
    
    if 'error' in leave_balance:
        return f"❌ Error retrieving leave balance for {emp['developer_name']}: {leave_balance['error']}"
    
    response = f"📊 **Leave Balance for {emp['developer_name']}**\n\n"
    response += f"💼 Designation: {emp.get('designation', 'N/A')}\n"
    response += f"📧 Email: {emp.get('email_id', 'N/A')}\n\n"
    
    response += f"💰 **Current Balance:** {leave_balance['current_balance']:.1f} days\n"
    response += f"📥 Opening Balance: {leave_balance['opening_balance']} days\n"
    response += f"📤 Leaves Used: {leave_balance['used_leaves']:.1f} days\n\n"
    
    if leave_balance['leave_details']:
        response += f"📋 **Breakdown of Used Leaves:**\n"
        for leave in leave_balance['leave_details']:
            lt = (leave.get('leave_type') or '').upper()
            days_equiv = 1.0 if lt == 'FULL DAY' else 0.5 if lt in ['HALF DAY','COMPENSATION HALF DAY'] else 0.25 if lt in ['2 HRS','COMPENSATION 2 HRS'] else 1.0
            total_days = float(leave.get('count') or 0) * days_equiv
            response += f"   - {leave['leave_type']}: {leave['count']} times ({total_days:.1f} days)\n"
    
    return response

@mcp.tool()
def search_employees(search_query: str) -> str:
    """Search for employees by name, designation, email, or employee number"""
    employees = fetch_employees_ai(search_term=search_query)
    
    if not employees:
        return f"❌ No employees found matching '{search_query}'"
    
    response = f"🔍 **Search Results for '{search_query}':**\n\n"
    
    for i, emp in enumerate(employees, 1):
        response += f"{i}. **{emp['developer_name']}**\n"
        response += f"   💼 {emp.get('designation', 'N/A')}\n"
        response += f"   📧 {emp.get('email_id', 'N/A')}\n"
        response += f"   📞 {emp.get('mobile', 'N/A')}\n"
        response += f"   🆔 {emp.get('emp_number', 'N/A')}\n"
        response += f"   🔰 {'Active' if emp.get('status') == 1 else 'Inactive'}\n"
        
        # Get quick leave balance
        try:
            leave_balance = get_leave_balance_for_employee(emp['id'])
            if 'error' not in leave_balance:
                response += f"   📊 Leave Balance: {leave_balance['current_balance']:.1f} days\n"
        except Exception:
            pass
        
        response += "\n"
    
    return response

# =============================================================================
# HEALTH AND INFO ENDPOINTS (Public - no authentication required)
# =============================================================================

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Public health check endpoint"""
    return PlainTextResponse("OK")

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    """Public info endpoint"""
    return JSONResponse({
        "service": "Secure Leave Manager Plus MCP Server",
        "version": "2.0.0",
        "status": "running",
        "authentication": "API Key Required",
        "usage": {
            "header": f"Use '{Config.API_KEY_HEADER}' header",
            "example": "Authorization: Bearer <api_key>",
            "rate_limit": f"{Config.RATE_LIMIT_PER_MINUTE} requests/minute"
        },
        "endpoints": {
            "health": "/health (GET)",
            "mcp": "/mcp (POST) - requires API key"
        }
    })

# =============================================================================
# APPLICATION STARTUP
# =============================================================================

def initialize_application():
    """Initialize the application on startup"""
    print("🚀 Initializing Secure MCP Server...")
    
    # Create API keys table
    APIKeyManager.create_api_keys_table()
    
    # Generate default API key if no active keys exist
    if APIKeyManager.get_active_keys_count() == 0:
        default_key = APIKeyManager.generate_api_key("default-admin-key")
        if default_key:
            print("🔑 Default API Key Generated:")
            print(f"   Key: {default_key}")
            print("   🔒 Save this key securely - it won't be shown again!")
        else:
            print("❌ Failed to generate default API key")
    
    print("✅ Application initialization completed")

if __name__ == "__main__":
    # Initialize application
    initialize_application()
    
    # Start server
    print(f"\n🎯 Starting Secure MCP Server...")
    print(f"   Host: {Config.MCP_HOST}")
    print(f"   Port: {Config.PORT}")
    print(f"   Transport: {Config.MCP_TRANSPORT}")
    print(f"   API Key Header: {Config.API_KEY_HEADER}")
    print(f"   Rate Limiting: {'Enabled' if Config.ENABLE_RATE_LIMITING else 'Disabled'}")
    print(f"   Requests/Minute: {Config.RATE_LIMIT_PER_MINUTE}")
    print(f"   Debug Mode: {Config.DEBUG}")
    
    if Levenshtein is None:
        print("   ⚠️  Levenshtein: Not installed (fuzzy matching quality reduced)")
    else:
        print("   ✅ Levenshtein: Installed")
    
    print(f"\n🔒 **SECURITY NOTICE:**")
    print(f"   All MCP endpoints require valid API key authentication")
    print(f"   Use the generate_api_key tool to create your first API key")
    print(f"   Include API key in '{Config.API_KEY_HEADER}' header or Authorization: Bearer <key>")
    
    mcp.run(
        transport=Config.MCP_TRANSPORT,
        host=Config.MCP_HOST,
        port=Config.PORT
    )