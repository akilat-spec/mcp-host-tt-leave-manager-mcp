import os
import re
import urllib.parse
from typing import List, Optional, Dict, Any
from difflib import SequenceMatcher
from datetime import datetime, date, timedelta

# Third-party imports with fallbacks
try:
    import mysql.connector
    from mysql.connector import Error
except ImportError:
    print("❌ mysql-connector-python not installed. Install with: pip install mysql-connector-python")
    raise

try:
    from fastmcp import FastMCP
except ImportError:
    print("❌ fastmcp not installed. Install with: pip install fastmcp")
    raise

# For authentication and responses
try:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
except ImportError:
    print("❌ starlette not installed. Install with: pip install starlette")
    raise

# Optional Levenshtein import
try:
    import Levenshtein
    LEVENSHTEIN_AVAILABLE = True
except ImportError:
    Levenshtein = None
    LEVENSHTEIN_AVAILABLE = False
    print("⚠️  python-levenshtein not installed. Fuzzy matching will use difflib only.")

# -------------------------------
# Configuration and Constants
# -------------------------------
API_KEYS = [key.strip() for key in os.environ.get("MCP_API_KEYS", "").split(",") if key.strip()]
REQUIRE_API_KEY = os.environ.get("MCP_REQUIRE_API_KEY", "true").lower() == "true"

# -------------------------------
# MCP server
# -------------------------------
mcp = FastMCP("LeaveManagerPlus")

# -------------------------------
# MySQL connection (reads from env)
# -------------------------------
def get_connection():
    """
    Read DB credentials from environment variables with proper error handling
    """
    try:
        connection = mysql.connector.connect(
            host=os.environ.get("DB_HOST", "103.174.10.72"),
            user=os.environ.get("DB_USER", "tt_crm_mcp"),
            password=os.environ.get("DB_PASSWORD", "F*PAtqhu@sg2w58n"),
            database=os.environ.get("DB_NAME", "tt_crm_mcp"),
            port=int(os.environ.get("DB_PORT", "3306")),
            autocommit=True,
            buffered=True  # This helps prevent "Unread result found" errors
        )
        
        # Test the connection
        if connection.is_connected():
            return connection
        else:
            raise Exception("Failed to establish database connection")
            
    except Error as e:
        print(f"❌ Database connection error: {e}")
        raise
    except Exception as e:
        print(f"❌ Unexpected database error: {e}")
        raise

def test_database_connection():
    """Test database connection with proper cleanup"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        return result is not None and result[0] == 1
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

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

        if LEVENSHTEIN_AVAILABLE and Levenshtein:
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
                first_name_part = emp_full_name.split()[0] if emp_full_name else ''
                last_name_part = ' '.join(emp_full_name.split()[1:]) if ' ' in emp_full_name else ''
                first_score = NameMatcher.similarity_score(search_parts['first'], first_name_part)
                last_score = NameMatcher.similarity_score(search_parts['last'], last_name_part)
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
# Core Employee Tools
# -------------------------------
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

@mcp.tool()
def get_work_report(name: str, days: int = 7, additional_context: Optional[str] = None) -> str:
    """Get work report for an employee for specified number of days"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}"

    emp = resolution['employee']
    work_reports = get_employee_work_report(emp['id'], days)
    
    response = f"📋 **Work Report for {emp['developer_name']}**\n"
    response += f"💼 Designation: {emp.get('designation', 'N/A')}\n"
    response += f"📅 Period: Last {days} days\n\n"
    
    if not work_reports:
        response += "No work reports found for the specified period."
        return response
    
    total_hours = 0.0
    for report in work_reports:
        hours = (report['total_time'] or 0) / 3600 if report.get('total_time') else 0.0
        total_hours += hours
        
        response += f"**{report['date']}** - {report.get('project_name', 'No Project')}\n"
        response += f"Client: {report.get('client_name', 'N/A')}\n"
        response += f"Task: {report['task'][:120]}{'...' if len(report.get('task','')) > 120 else ''}\n"
        if report.get('description'):
            response += f"Details: {report['description'][:120]}{'...' if len(report.get('description','')) > 120 else ''}\n"
        response += f"Hours: {hours:.1f}h\n"
        response += "---\n"
    
    response += f"\n**Total Hours ({days} days): {total_hours:.1f}h**\n"
    response += f"Average per day: { (total_hours/days):.1f}h" if days > 0 else ""
    
    return response

@mcp.tool()
def get_leave_history(name: str, additional_context: Optional[str] = None) -> str:
    """Get leave history for an employee"""
    resolution = resolve_employee_ai(name, additional_context)
    
    if resolution['status'] == 'not_found':
        return f"❌ No employee found matching '{name}'."
    
    if resolution['status'] == 'ambiguous':
        options_text = format_employee_options(resolution['employees'])
        return f"🔍 {resolution['message']}\n\n{options_text}"

    emp = resolution['employee']
    leave_requests = get_employee_leave_requests(emp['id'], limit=100)
    
    response = f"🏖️  **Leave History for {emp['developer_name']}**\n"
    response += f"💼 Designation: {emp.get('designation', 'N/A')}\n\n"
    
    if not leave_requests:
        response += "No leave requests found."
        return response
    
    approved_count = sum(1 for lr in leave_requests if lr['status'] == 'Approved')
    pending_count = sum(1 for lr in leave_requests if lr['status'] in ['Requested', 'Pending'])
    declined_count = sum(1 for lr in leave_requests if lr['status'] == 'Declined')
    
    response += f"📊 Summary: {approved_count} Approved, {pending_count} Pending, {declined_count} Declined\n\n"
    
    for leave in leave_requests[:40]:
        status_icon = "✅" if leave['status'] == 'Approved' else "⏳" if leave['status'] in ['Requested', 'Pending'] else "❌"
        response += f"**{leave['date_of_leave']}** - {leave['leave_type']} {status_icon}\n"
        if leave.get('dev_comments'):
            response += f"Reason: {leave['dev_comments']}\n"
        if leave.get('admin_comments') and leave['status'] != 'Pending':
            response += f"Admin Note: {leave['admin_comments']}\n"
        response += "---\n"
    
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

# -------------------------------
# MCP Endpoint + Health
# -------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint that shows authentication status"""
    health_info = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "authentication_required": REQUIRE_API_KEY,
        "api_keys_configured": len(API_KEYS) > 0,
        "levenshtein_available": LEVENSHTEIN_AVAILABLE,
        "database": "unknown"
    }
    
    # Test database connection
    try:
        if test_database_connection():
            health_info["database"] = "connected"
        else:
            health_info["database"] = "disconnected"
    except Exception as e:
        health_info["database"] = f"error: {str(e)}"
    
    return JSONResponse(health_info)

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    return JSONResponse({
        "message": "Leave Manager + HR + Company Management MCP Server",
        "status": "running",
        "version": "1.0.0",
        "authentication_required": REQUIRE_API_KEY,
        "documentation": "Use X-API-Key header or Bearer token for authentication"
    })

# -------------------------------
# Run MCP server
# -------------------------------
if __name__ == "__main__":
    # Print startup information
    print("🔐 Secure MCP Leave Manager Server")
    print("=" * 50)
    
    if LEVENSHTEIN_AVAILABLE:
        print("✅ python-levenshtein: Available")
    else:
        print("⚠️  python-levenshtein: Not available (using difflib fallback)")
    
    # Check API keys
    if REQUIRE_API_KEY:
        if API_KEYS:
            print(f"🔐 API Key Authentication: ENABLED ({len(API_KEYS)} keys configured)")
            print(f"   Keys: {', '.join(['*' * 8 for _ in API_KEYS])}")
        else:
            print("⚠️  API Key Authentication: REQUIRED BUT NO KEYS CONFIGURED")
            print("   Set MCP_API_KEYS environment variable or disable with MCP_REQUIRE_API_KEY=false")
            # Continue anyway for development
            print("   ⚠️  Continuing without API keys - NOT RECOMMENDED FOR PRODUCTION")
    else:
        print("🔓 API Key Authentication: DISABLED")
    
    # Test database connection
    print("\n🔌 Testing database connection...")
    try:
        if test_database_connection():
            print("✅ Database connection: Successful")
        else:
            print("❌ Database connection: Failed")
            exit(1)
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        exit(1)
    
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8081"))

    print(f"\n🚀 Starting server on {host}:{port}...")
    print(f"📡 Transport: {transport}")
    print("=" * 50)
    
    mcp.run(transport=transport, host=host, port=port)