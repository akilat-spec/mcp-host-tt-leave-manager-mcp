import os
import logging
import socket
from typing import Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# Import your modules
from config import security_config
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

# Add authentication middleware
mcp.app.add_middleware(APIKeyMiddleware)

# Initialize services
employee_service = EmployeeService()

# -------------------------------
# Health and Info Endpoints
# -------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Comprehensive health check endpoint"""
    from utils.database import DatabaseConnection
    
    health_status = {
        "status": "healthy",
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "service": "Leave Manager MCP Server",
        "version": "1.16.1",
        "authentication": {
            "required": security_config.require_api_key,
            "enabled": security_config.is_authentication_enabled,
            "keys_configured": len(security_config.api_keys)
        },
        "database": {
            "connected": DatabaseConnection.test_connection()
        }
    }
    return JSONResponse(health_status)

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    """Root endpoint with API information"""
    return JSONResponse({
        "message": "Leave Manager + HR + Company Management MCP Server",
        "status": "running",
        "version": "1.16.1",
        "authentication_required": security_config.require_api_key,
        "endpoints": {
            "health": "/health",
            "mcp": "/mcp"
        },
        "authentication": "Use x-api-key header or Authorization: Bearer <token>"
    })

# -------------------------------
# MCP Tools
# -------------------------------
@mcp.tool()
def get_employee_details(name: str, additional_context: Optional[str] = None) -> str:
    """Get comprehensive details for an employee"""
    try:
        employees = employee_service.fetch_employees(search_term=name)
        
        if not employees:
            return f"❌ No employee found matching '{name}'."
        
        if len(employees) == 1:
            employee = employees[0]
            leave_balance = employee_service.get_leave_balance(employee.id)
            
            response = f"✅ **Employee Details**\n\n"
            response += f"👤 **{employee.developer_name}**\n"
            response += f"🆔 Employee ID: {employee.id} | Employee #: {employee.emp_number or 'N/A'}\n"
            response += f"💼 Designation: {employee.designation or 'N/A'}\n"
            response += f"📧 Email: {employee.email_id or 'N/A'}\n"
            response += f"📞 Mobile: {employee.mobile or 'N/A'}\n"
            response += f"🩸 Blood Group: {employee.blood_group or 'N/A'}\n"
            response += f"📅 Date of Joining: {employee.doj or 'N/A'}\n"
            response += f"🔰 Status: {'Active' if employee.is_active else 'Inactive'}\n\n"
            
            response += f"📊 **Leave Balance:** {leave_balance.current_balance:.1f} days\n"
            response += f"   - Opening Balance: {leave_balance.opening_balance}\n"
            response += f"   - Leaves Used: {leave_balance.used_leaves:.1f} days\n"
            
            return response
        else:
            options = []
            for i, emp in enumerate(employees, 1):
                option = f"{i}. 👤 {emp.developer_name}"
                if emp.designation:
                    option += f" | 💼 {emp.designation}"
                if emp.email_id:
                    option += f" | 📧 {emp.email_id}"
                options.append(option)
            
            options_text = "\n".join(options)
            return f"🔍 Found {len(employees)} employees. Please specify:\n\n{options_text}"
            
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
            options = "\n".join([f"{i}. {emp.developer_name} ({emp.designation or 'N/A'})" 
                               for i, emp in enumerate(employees, 1)])
            return f"🔍 Multiple employees found. Please specify:\n\n{options}"
        
        employee = employees[0]
        leave_balance = employee_service.get_leave_balance(employee.id)
        
        response = f"📊 **Leave Balance for {employee.developer_name}**\n\n"
        response += f"💼 Designation: {employee.designation or 'N/A'}\n"
        response += f"📧 Email: {employee.email_id or 'N/A'}\n\n"
        
        response += f"💰 **Current Balance:** {leave_balance.current_balance:.1f} days\n"
        response += f"📥 Opening Balance: {leave_balance.opening_balance} days\n"
        response += f"📤 Leaves Used: {leave_balance.used_leaves:.1f} days\n"
        
        return response
        
    except Exception as e:
        logger.error(f"Error in get_leave_balance: {e}")
        return f"❌ Error retrieving leave balance: {str(e)}"

# Add more tools as needed...

# -------------------------------
# Application Startup
# -------------------------------
if __name__ == "__main__":
    # Display startup information
    logger.info("Starting Leave Manager Plus MCP Server")
    
    # Security configuration info
    if security_config.require_api_key:
        if security_config.api_keys:
            logger.info(f"🔐 API Key Authentication: ENABLED ({len(security_config.api_keys)} keys configured)")
        else:
            logger.warning("⚠️  API Key Authentication: REQUIRED but no keys configured!")
    else:
        logger.info("🔓 API Key Authentication: DISABLED")
    
    # Database connection test
    from utils.database import DatabaseConnection
    if DatabaseConnection.test_connection():
        logger.info("✅ Database connection: SUCCESS")
    else:
        logger.error("❌ Database connection: FAILED")
    
    # Server configuration
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    
    logger.info(f"🚀 Server starting on {host}:{port} with {transport} transport")
    
    # Start the MCP server
    mcp.run(transport=transport, host=host, port=port)