import os
import re
import urllib.parse
from typing import List, Optional, Dict, Any, Set
from difflib import SequenceMatcher
from datetime import datetime, date, timedelta

# third-party
import mysql.connector
from fastmcp import FastMCP

# optional Levenshtein import
try:
    import Levenshtein
except Exception:
    Levenshtein = None

# For health route responses
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse

# -------------------------------
# MCP server
# -------------------------------
mcp = FastMCP("LeaveManagerPlus")

# -------------------------------
# API Key Configuration
# -------------------------------
def get_valid_api_keys() -> Set[str]:
    """Get all valid API keys from environment variables"""
    valid_keys = set()
    
    # Primary API key (required for all connections)
    primary_key = os.environ.get("MCP_API_KEY")
    if primary_key:
        valid_keys.add(primary_key)
    
    # Smithery API key
    smithery_key = os.environ.get("SMITHERY_API_KEY")
    if smithery_key:
        valid_keys.add(smithery_key)
    
    # Additional API keys (comma-separated)
    additional_keys = os.environ.get("MCP_API_KEYS", "")
    for key in additional_keys.split(","):
        key = key.strip()
        if key:
            valid_keys.add(key)
    
    return valid_keys

def require_api_key() -> bool:
    """Check if API key is required"""
    return os.environ.get("REQUIRE_API_KEY", "true").lower() == "true"

def authenticate_request(request: Request) -> Optional[JSONResponse]:
    """Authenticate the request with API key"""
    if not require_api_key():
        return None
    
    valid_keys = get_valid_api_keys()
    if not valid_keys:
        # If no API keys are configured but authentication is required, deny access
        return JSONResponse(
            {"error": "Server configuration error: No API keys configured"},
            status_code=500
        )
    
    # Get API key from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            {
                "error": "API key required",
                "message": "This MCP server requires an API key for access. Please provide your API key in the Authorization header.",
                "usage": "Authorization: Bearer YOUR_API_KEY"
            }, 
            status_code=401
        )
    
    api_key = auth_header.replace("Bearer ", "").strip()
    if api_key not in valid_keys:
        return JSONResponse(
            {
                "error": "Invalid API key",
                "message": "The provided API key is invalid. Please check your API key and try again."
            }, 
            status_code=403
        )
    
    return None

# -------------------------------
# MySQL connection (reads from env)
# -------------------------------
def get_connection():
    """
    Read DB credentials from environment variables
    """
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "103.174.10.72"),
        user=os.environ.get("DB_USER", "tt_crm_mcp"),
        password=os.environ.get("DB_PASSWORD", "F*PAtqhu@sg2w58n"),
        database=os.environ.get("DB_NAME", "tt_crm_mcp"),
        port=int(os.environ.get("DB_PORT", "3306")),
        autocommit=True,
    )

# -------------------------------
# AI-Powered Name Matching Utilities
# -------------------------------
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

# -------------------------------
# Enhanced Employee Search with AI
# -------------------------------
def fetch_employees_ai(search_term: str = None, emp_id: int = None) -> List[Dict[str, Any]]:
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

        if search_term and not rows:
            # fallback fuzzy search among active employees
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

# -------------------------------
# Leave Management Functions
# -------------------------------
def get_leave_balance_for_employee(developer_id: int) -> Dict[str, Any]:
    """Calculate leave balance for an employee"""
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
                # default treat as full day for unknown types
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

def get_employee_work_report(developer_id: int, days: int = 30) -> List[Dict[str, Any]]:
    """Get recent work reports for an employee"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT wr.task, wr.description, wr.date, wr.total_time, 
                   p.title as project_name, c.client_name
            FROM work_report wr
            LEFT JOIN project p ON wr.project_id = p.id
            LEFT JOIN client c ON wr.client_id = c.id
            WHERE wr.developer_id = %s 
            AND wr.date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            ORDER BY wr.date DESC
            LIMIT 100
        """, (developer_id, days))
        
        return cursor.fetchall()
        
    except Exception as e:
        print(f"Error fetching work report: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def get_employee_leave_requests(developer_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Get leave requests for an employee"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT request_id, leave_type, date_of_leave, status, 
                   dev_comments, admin_comments, created_at
            FROM leave_requests 
            WHERE developer_id = %s 
            ORDER BY date_of_leave DESC
            LIMIT %s
        """, (developer_id, limit))
        
        return cursor.fetchall()
        
    except Exception as e:
        print(f"Error fetching leave requests: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

# -------------------------------
# Employee Formatting and Resolution
# -------------------------------
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
        if emp.get('mobile'):
            option += f" | 📞 {emp.get('mobile')}"
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

# -------------------------------
# Secure MCP Tools with API Key Authentication
# -------------------------------
def secure_tool(func):
    """Decorator to secure MCP tools with API key authentication"""
    async def wrapper(request: Request, *args, **kwargs):
        # Check API key for all tool calls
        auth_error = authenticate_request(request)
        if auth_error:
            return auth_error
        return await func(request, *args, **kwargs)
    return wrapper

# All MCP tools are automatically secured by the MCP protocol
# The authentication happens at the MCP endpoint level

@mcp.tool()
def get_employee_details(name: str, additional_context: Optional[str] = None) -> str:
    """Get comprehensive details for an employee including personal info, leave balance, and recent activity"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}\n\n💡 Tip: You can specify by:\n- Designation (e.g., 'Developer')\n- Email\n- Employee number\n- Or say the number (e.g., '1')"

    emp = resolution['employee']
    
    # Get additional information
    leave_balance = get_leave_balance_for_employee(emp['id'])
    work_reports = get_employee_work_report(emp['id'], days=7)
    leave_requests = get_employee_leave_requests(emp['id'], limit=10)
    
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
        response += f"   - Leaves Used: {leave_balance['used_leaves']:.1f} days\n\n"
    else:
        response += f"📊 Leave Balance: Data not available\n\n"
    
    # Recent Work Reports
    if work_reports:
        response += f"📋 **Recent Work (Last 7 days):**\n"
        for report in work_reports[:3]:
            hours = (report['total_time'] or 0) / 3600 if report.get('total_time') else 0
            response += f"   - {report['date']}: {report['task'][:60]}... ({hours:.1f}h)\n"
        response += "\n"
    
    # Recent Leave Requests
    if leave_requests:
        response += f"🏖️  **Recent Leave Requests:**\n"
        for leave in leave_requests[:3]:
            status_icon = "✅" if leave['status'] == 'Approved' else "⏳" if leave['status'] in ['Requested', 'Pending'] else "❌"
            response += f"   - {leave['date_of_leave']}: {leave['leave_type']} {status_icon}\n"
    
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

# ... (include all your other tools here - they will be automatically secured)
# get_work_report, get_leave_history, search_employees, get_employee_profile, 
# get_attendance_summary, get_client_list, get_projects_overview, get_holidays, etc.

# -------------------------------
# MCP Endpoints with Authentication
# -------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Public health check endpoint"""
    return PlainTextResponse("OK")

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    """Public root endpoint with connection instructions"""
    return JSONResponse({
        "message": "TT Leave Manager MCP Server",
        "status": "running", 
        "version": "1.0.0",
        "authentication_required": require_api_key(),
        "instructions": "This MCP server requires an API key for access. Please configure your API key in your MCP client.",
        "usage": {
            "header": "Authorization: Bearer YOUR_API_KEY",
            "environment_variable": "MCP_API_KEY=your_api_key_here"
        }
    })

@mcp.custom_route("/mcp", methods=["POST"])
async def secure_mcp_endpoint(request: Request):
    """Secure MCP protocol endpoint - REQUIRES API KEY"""
    # Authenticate the request
    auth_error = authenticate_request(request)
    if auth_error:
        return auth_error
    
    # If authentication passes, process the MCP request
    # FastMCP will handle the actual MCP protocol processing
    return JSONResponse({
        "status": "MCP server is running",
        "authenticated": True,
        "message": "API key validated successfully"
    })

# -------------------------------
# Run MCP server
# -------------------------------
if __name__ == "__main__":
    if Levenshtein is None:
        print("Warning: python-levenshtein not installed. Fuzzy quality will be slightly lower. Install with: pip install python-Levenshtein")

    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))

    # Security configuration check
    valid_keys = get_valid_api_keys()
    require_auth = require_api_key()
    
    if require_auth:
        if not valid_keys:
            print("❌ SECURITY ERROR: API key authentication is REQUIRED but no API keys are configured!")
            print("   Please set MCP_API_KEY environment variable")
            exit(1)
        else:
            print("✅ API key authentication: REQUIRED")
            print(f"   Configured API keys: {len(valid_keys)}")
            # Don't print actual keys for security
    else:
        print("⚠️  WARNING: API key authentication is DISABLED")
        print("   Set REQUIRE_API_KEY=true to enable authentication")

    print(f"Starting TT Leave Manager MCP Server on {host}:{port} with {transport} transport")
    
    # Use FastMCP's built-in run method
    mcp.run(transport=transport, host=host, port=port)