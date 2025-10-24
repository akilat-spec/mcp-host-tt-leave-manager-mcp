# Secure TT Leave Manager MCP Server

A highly secure Model Context Protocol server for employee leave management with mandatory API key authentication.

## 🔐 Security Features

- **Mandatory API Key Authentication** - No access without valid API key
- **Bearer Token Authentication** - Standard HTTP authentication
- **Configurable API Keys** - Multiple keys supported
- **Secure Middleware** - All endpoints protected
- **Health Check** - Public health endpoint for monitoring

## 🚀 Deployment on Smithery.ai

### 1. Environment Variables

Configure these required environment variables in Smithery:

```env
DB_HOST=103.174.10.72
DB_USER=tt_crm_mcp  
DB_PASSWORD=F*PAtqhu@sg2w58n
DB_NAME=tt_crm_mcp
DB_PORT=3306
MCP_API_KEYS=0YUrS7QY3LMBWOb68f1Vswk3B1df9B8L,xilUGWevlvAarM1rOtDvrWCQR2lwH3B3
REQUIRE_API_KEY=true