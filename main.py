import os
import re
import json
from typing import List, Optional, Dict, Any, Set
from difflib import SequenceMatcher
from datetime import datetime, date, timedelta
import logging

# Third-party imports
import mysql.connector
from fastmcp import FastMCP
from pydantic import BaseModel

# Optional Levenshtein import
try:
    import Levenshtein
    LEVENSHTEIN_AVAILABLE = True
except ImportError:
    Levenshtein = None
    LEVENSHTEIN_AVAILABLE = False

# For HTTP responses
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware import Middleware

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secure-leave-manager")

# -------------------------------
# Configuration Models
# -------------------------------
class ServerConfig(BaseModel):
    db_host: str
    db_user: str
    db_password: str
    db_name: str
    db_port: int = 3306
    require_api_key: bool = True
    valid_api_keys: Set[str] = set()

# -------------------------------
# Configuration Loader
# -------------------------------
def load_config() -> ServerConfig:
    """Load configuration from environment variables"""
    
    # Database configuration
    db_host = os.environ.get("DB_HOST", "103.174.10.72")
    db_user = os.environ.get("DB_USER", "tt_crm_mcp")
    db_password = os.environ.get("DB_PASSWORD", "F*PAtqhu@sg2w58n")
    db_name = os.environ.get("DB_NAME", "tt_crm_mcp")
    db_port = int(os.environ.get("DB_PORT", "3306"))
    
    # API Key configuration
    require_api_key = os.environ.get("REQUIRE_API_KEY", "true").lower() == "true"
    
    # Collect all valid API keys
    valid_api_keys = set()
    
    # Primary API key
    primary_key = os.environ.get("MCP_API_KEY")
    if primary_key:
        valid_api_keys.add(primary_key)
    
    # Smithery API key (provided by Smithery platform)
    smithery_key = os.environ.get("SMITHERY_API_KEY")
    if smithery_key:
        valid_api_keys.add(smithery_key)
    
    # Additional API keys (comma-separated)
    additional_keys = os.environ.get("MCP_API_KEYS", "")
    for key in additional_keys.split(","):
        key = key.strip()
        if key:
            valid_api_keys.add(key)
    
    # For Smithery deployment, ensure we have at least one API key if required
    if require_api_key and not valid_api_keys:
        logger.warning("API key authentication required but no API keys configured!")
    
    return ServerConfig(
        db_host=db_host,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
        db_port=db_port,
        require_api_key=require_api_key,
        valid_api_keys=valid_api_keys
    )

# Load configuration
config = load_config()

# -------------------------------
# Authentication Middleware
# -------------------------------
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip authentication for health check and root endpoint
        if request.url.path in ["/health", "/"]:
            return await call_next(request)
        
        # Check if API key is required
        if not config.require_api_key:
            return await call_next(request)
        
        # Validate API keys exist
        if not config.valid_api_keys:
            return JSONResponse(
                {
                    "error": "Server configuration error",
                    "message": "No API keys configured. Please contact administrator."
                },
                status_code=500
            )
        
        # Get API key from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                {
                    "error": "Authentication required",
                    "message": "Valid API key required for access",
                    "usage": "Include: Authorization: Bearer YOUR_API_KEY"
                },
                status_code=401
            )
        
        api_key = auth_header.replace("Bearer ", "").strip()
        if api_key not in config.valid_api_keys:
            return JSONResponse(
                {
                    "error": "Invalid API key",
                    "message": "The provided API key is invalid or expired"
                },
                status_code=403
            )
        
        # Authentication successful
        response = await call_next(request)
        return response

# -------------------------------
# MCP Server Initialization
# -------------------------------
mcp = FastMCP(
    "SecureLeaveManager",
    middleware=[Middleware(AuthMiddleware)]
)

# -------------------------------
# Database Connection
# -------------------------------
def get_connection():
    """Create database connection using configured credentials"""
    return mysql.connector.connect(
        host=config.db_host,
        user=config.db_user,
        password=config.db_password,
        database=config.db_name,
        port=config.db_port,
        autocommit=True,
    )

# -------------------------------
# AI-Powered Name Matching
# -------------------------------
class NameMatcher:
    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize name for comparison"""
        name = (name or "").lower().strip()
        name = re.sub(r'[^\w\s]', '', name)
        name = re.sub(r'\s+', ' ', name)
        return name

    @staticmethod
    def similarity_score(name1: str, name2: str) -> float:
        """Calculate similarity score between two names"""
        name1_norm = NameMatcher.normalize_name(name1)
        name2_norm = NameMatcher.normalize_name(name2)

        if LEVENSHTEIN_AVAILABLE:
            try:
                dist = Levenshtein.distance(name1_norm, name2_norm)
                max_len = max(len(name1_norm), len(name2_norm), 1)
                levenshtein_sim = 1 - (dist / max_len)
            except Exception:
                levenshtein_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        else:
            levenshtein_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()

        sequence_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        combined_score = (levenshtein_sim * 0.6) + (sequence_sim * 0.4)
        return combined_score

    @staticmethod
    def fuzzy_match_employee(search_name: str, employees: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
        """Fuzzy match employee names"""
        matches = []
        
        for emp in employees:
            emp_full_name = f"{emp.get('developer_name','')}".strip()
            best_score = NameMatcher.similarity_score(search_name, emp_full_name)
            
            if best_score >= threshold:
                matches.append({
                    'employee': emp, 
                    'score': best_score, 
                    'match_type': 'fuzzy'
                })

        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches

# -------------------------------
# Employee Data Access
# -------------------------------
def fetch_employees_ai(search_term: str = None, emp_id: int = None) -> List[Dict[str, Any]]:
    """Fetch employees with AI-powered search"""
    conn = get_connection()
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

        # Fallback to fuzzy search if no exact matches
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
        logger.error(f"Database error in fetch_employees_ai: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def get_leave_balance_for_employee(developer_id: int) -> Dict[str, Any]:
    """Calculate leave balance for employee"""
    conn = get_connection()
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

# -------------------------------
# Employee Resolution
# -------------------------------
def format_employee_options(employees: List[Dict[str, Any]]) -> str:
    """Format employee list for user selection"""
    options = []
    for i, emp in enumerate(employees, 1):
        option = f"{i}. 👤 {emp.get('developer_name','Unknown')}"
        if emp.get('designation'):
            option += f" | 💼 {emp.get('designation')}"
        if emp.get('email_id'):
            option += f" | 📧 {emp.get('email_id')}"
        status = "Active" if emp.get('status') == 1 else "Inactive"
        option += f" | 🔰 {status}"
        options.append(option)
    return "\n".join(options)

def resolve_employee_ai(search_name: str, additional_context: str = None) -> Dict[str, Any]:
    """Resolve employee name with AI matching"""
    employees = fetch_employees_ai(search_term=search_name)

    if not employees:
        return {'status': 'not_found', 'message': f"No employees found matching '{search_name}'"}

    if len(employees) == 1:
        return {'status': 'resolved', 'employee': employees[0]}

    # Use additional context to disambiguate
    if additional_context:
        context_lower = (additional_context or '').lower()
        filtered_employees = []
        for emp in employees:
            designation = (emp.get('designation') or '').lower()
            email = (emp.get('email_id') or '').lower()
            if (context_lower in designation or context_lower in email):
                filtered_employees.append(emp)
        
        if len(filtered_employees) == 1:
            return {'status': 'resolved', 'employee': filtered_employees[0]}

    return {
        'status': 'ambiguous',
        'employees': employees,
        'message': f"Found {len(employees)} employees. Please specify:"
    }

# -------------------------------
# MCP Tools (All Require Authentication via Middleware)
# -------------------------------
@mcp.tool()
def get_employee_details(name: str, additional_context: Optional[str] = None) -> str:
    """Get comprehensive details for an employee including personal info and leave balance"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}"

    emp = resolution['employee']
    leave_balance = get_leave_balance_for_employee(emp['id'])
    
    response = f"✅ **Employee Details**\n\n"
    response += f"👤 **{emp['developer_name']}**\n"
    response += f"🆔 Employee ID: {emp['id']} | Employee #: {emp.get('emp_number', 'N/A')}\n"
    response += f"💼 Designation: {emp.get('designation', 'N/A')}\n"
    response += f"📧 Email: {emp.get('email_id', 'N/A')}\n"
    response += f"📞 Mobile: {emp.get('mobile', 'N/A')}\n"
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
    response += f"💰 Current Balance: {leave_balance['current_balance']:.1f} days\n"
    response += f"📥 Opening Balance: {leave_balance['opening_balance']} days\n"
    response += f"📤 Leaves Used: {leave_balance['used_leaves']:.1f} days\n"
    
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
        response += f"   🔰 {'Active' if emp.get('status') == 1 else 'Inactive'}\n\n"
    
    return response

@mcp.tool()
def get_employee_profile(name: str, additional_context: Optional[str] = None) -> str:
    """Get extended HR profile for an employee"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}"

    emp = resolution['employee']
    
    response = f"📇 **HR Profile: {emp['developer_name']}**\n"
    response += f"🆔 ID: {emp['id']} | Emp#: {emp.get('emp_number','N/A')}\n"
    response += f"💼 Designation: {emp.get('designation','N/A')}\n"
    response += f"📅 DOJ: {emp.get('doj','N/A')}\n"
    response += f"🏥 PF Enabled: {'Yes' if emp.get('is_pf_enabled') in [1,'1',True] else 'No'}\n"
    response += f"📧 Email: {emp.get('email_id','N/A')}\n"
    response += f"📞 Mobile: {emp.get('mobile','N/A')}\n"
    
    if 'opening_leave_balance' in emp:
        try:
            response += f"📊 Opening Leave Balance: {float(emp.get('opening_leave_balance') or 0):.1f} days\n"
        except Exception:
            pass
    
    return response

# -------------------------------
# HTTP Endpoints
# -------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Public health check endpoint"""
    return PlainTextResponse("OK")

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    """Public root endpoint with server information"""
    return JSONResponse({
        "message": "Secure TT Leave Manager MCP Server",
        "status": "running",
        "version": "2.0.0",
        "authentication_required": config.require_api_key,
        "features": [
            "Employee Management",
            "Leave Balance Tracking", 
            "HR Operations",
            "AI-Powered Search"
        ],
        "authentication": {
            "required": config.require_api_key,
            "method": "Bearer Token",
            "header": "Authorization: Bearer YOUR_API_KEY"
        }
    })

# -------------------------------
# Server Startup
# -------------------------------
if __name__ == "__main__":
    # Log configuration status
    logger.info("=== Secure TT Leave Manager MCP Server ===")
    logger.info(f"Database: {config.db_host}:{config.db_port}")
    logger.info(f"API Authentication: {'ENABLED' if config.require_api_key else 'DISABLED'}")
    
    if config.require_api_key:
        if config.valid_api_keys:
            logger.info(f"Configured API keys: {len(config.valid_api_keys)}")
        else:
            logger.error("❌ API authentication required but no API keys configured!")
            exit(1)
    else:
        logger.warning("⚠️  API authentication is DISABLED - anyone can access the server!")
    
    if not LEVENSHTEIN_AVAILABLE:
        logger.warning("python-levenshtein not installed. Fuzzy matching quality may be reduced.")
    
    # Start server
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    
    logger.info(f"Starting server on {host}:{port} with {transport} transport")
    mcp.run(transport=transport, host=host, port=port)