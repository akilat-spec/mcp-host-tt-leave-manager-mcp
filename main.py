import os
import logging
import socket
from typing import Optional
import time

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

# Import directly from modules
from config.security import security_config
from middleware.auth import APIKeyMiddleware
from services.employee_service import EmployeeService

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP("LeaveManagerPlus")

# Add CORS middleware to allow all origins (required for MCP)
mcp.app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Add authentication middleware (after CORS)
mcp.app.add_middleware(APIKeyMiddleware)

# Initialize services (but don't test database on import)
employee_service = EmployeeService()

# Health endpoint (fast, no database check initially)
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Fast health check endpoint"""
    try:
        return JSONResponse({
            "status": "healthy",
            "service": "Leave Manager MCP Server",
            "version": "1.16.1",
            "timestamp": time.time()
        })
    except Exception as e:
        return JSONResponse({
            "status": "unhealthy",
            "error": str(e)
        }, status_code=500)

# Detailed health check with database
@mcp.custom_route("/health/detailed", methods=["GET"])
async def detailed_health_check(request: Request) -> JSONResponse:
    """Detailed health check with database connection test"""
    try:
        from utils.database import DatabaseConnection
        db_connected = DatabaseConnection.test_connection()
        return JSONResponse({
            "status": "healthy",
            "service": "Leave Manager MCP Server",
            "version": "1.16.1",
            "authentication_required": security_config.require_api_key,
            "database_connected": db_connected,
            "timestamp": time.time()
        })
    except Exception as e:
        return JSONResponse({
            "status": "unhealthy",
            "error": str(e)
        }, status_code=500)

# Root endpoint
@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    return JSONResponse({
        "message": "Leave Manager MCP Server",
        "status": "running",
        "version": "1.16.1",
        "authentication_required": security_config.require_api_key,
        "endpoints": {
            "health": "/health",
            "health_detailed": "/health/detailed",
            "mcp": "/mcp"
        }
    })

# MCP Tools with better error handling
@mcp.tool()
def get_employee_details(name: str, additional_context: Optional[str] = None) -> str:
    """Get comprehensive details for an employee"""
    try:
        employees = employee_service.fetch_employees(search_term=name)
        
        if not employees:
            return f"❌ No employee found matching '{name}'."
        
        if len(employees) == 1:
            employee = employees[0]
            leave_balance = employee_service.get_leave_balance(employee['id'])
            
            response = f"✅ **Employee Details**\n\n"
            response += f"👤 **{employee['developer_name']}**\n"
            response += f"🆔 Employee ID: {employee['id']} | Employee #: {employee.get('emp_number', 'N/A')}\n"
            response += f"💼 Designation: {employee.get('designation', 'N/A')}\n"
            response += f"📧 Email: {employee.get('email_id', 'N/A')}\n"
            response += f"📞 Mobile: {employee.get('mobile', 'N/A')}\n"
            response += f"🩸 Blood Group: {employee.get('blood_group', 'N/A')}\n"
            response += f"📅 Date of Joining: {employee.get('doj', 'N/A')}\n"
            response += f"🔰 Status: {'Active' if employee.get('status') == 1 else 'Inactive'}\n\n"
            
            response += f"📊 **Leave Balance:** {leave_balance['current_balance']:.1f} days\n"
            response += f"   - Opening Balance: {leave_balance['opening_balance']}\n"
            response += f"   - Leaves Used: {leave_balance['used_leaves']:.1f} days\n"
            
            return response
        else:
            options = []
            for i, emp in enumerate(employees, 1):
                option = f"{i}. 👤 {emp['developer_name']}"
                if emp.get('designation'):
                    option += f" | 💼 {emp['designation']}"
                if emp.get('email_id'):
                    option += f" | 📧 {emp['email_id']}"
                options.append(option)
            
            return f"🔍 Found {len(employees)} employees. Please specify:\n\n" + "\n".join(options)
            
    except Exception as e:
        logger.error(f"Error in get_employee_details: {e}")
        return f"❌ Error retrieving employee details: {str(e)}"

@mcp.tool()
def get_leave_balance(name: str, additional_context: Optional[str] = None) -> str:
    """Get detailed leave balance for an employee"""
    try:
        employees = employee_service.fetch_employees(search_term=name)
        
        if not employees:
            return f"❌ No employee found matching '{name}'."
        
        if len(employees) > 1:
            options = "\n".join([f"{i}. {emp['developer_name']} ({emp.get('designation', 'N/A')})" 
                               for i, emp in enumerate(employees, 1)])
            return f"🔍 Multiple employees found. Please specify:\n\n{options}"
        
        employee = employees[0]
        leave_balance = employee_service.get_leave_balance(employee['id'])
        
        response = f"📊 **Leave Balance for {employee['developer_name']}**\n\n"
        response += f"💼 Designation: {employee.get('designation', 'N/A')}\n"
        response += f"📧 Email: {employee.get('email_id', 'N/A')}\n\n"
        
        response += f"💰 **Current Balance:** {leave_balance['current_balance']:.1f} days\n"
        response += f"📥 Opening Balance: {leave_balance['opening_balance']} days\n"
        response += f"📤 Leaves Used: {leave_balance['used_leaves']:.1f} days\n"
        
        return response
        
    except Exception as e:
        logger.error(f"Error in get_leave_balance: {e}")
        return f"❌ Error retrieving leave balance: {str(e)}"

@mcp.tool()
def search_employees(search_query: str) -> str:
    """Search for employees by name, designation, email, or employee number"""
    try:
        employees = employee_service.fetch_employees(search_term=search_query)
        
        if not employees:
            return f"❌ No employees found matching '{search_query}'"
        
        response = f"🔍 **Search Results for '{search_query}':**\n\n"
        
        for i, emp in enumerate(employees, 1):
            response += f"{i}. **{emp['developer_name']}**\n"
            response += f"   💼 {emp.get('designation', 'N/A')}\n"
            response += f"   📧 {emp.get('email_id', 'N/A')}\n"
            response += f"   📞 {emp.get('mobile', 'N/A')}\n"
            response += f"   🆔 {emp.get('emp_number', 'N/A')}\n"
            response += f"   🔰 {'Active' if emp.get('status') == 1 else 'Inactive'}\n\n"
        
        return response
        
    except Exception as e:
        logger.error(f"Error in search_employees: {e}")
        return f"❌ Error searching employees: {str(e)}"

if __name__ == "__main__":
    logger.info("Starting Leave Manager Plus MCP Server")
    
    # Security info
    if security_config.require_api_key:
        if security_config.api_keys:
            logger.info(f"🔐 API Key Authentication: ENABLED")
        else:
            logger.warning("⚠️  API Key Authentication: REQUIRED but no keys configured!")
    else:
        logger.info("🔓 API Key Authentication: DISABLED")
    
    # Fast startup - don't block on database connection
    logger.info("🚀 Server starting (database connection will be tested on first request)")
    
    # Server configuration
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    
    logger.info(f"🌐 Server configured for {transport} transport on {host}:{port}")
    logger.info("📡 CORS enabled for all origins")
    
    # Start the MCP server
    mcp.run(transport=transport, host=host, port=port)