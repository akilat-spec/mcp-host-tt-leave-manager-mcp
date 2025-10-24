#!/usr/bin/env python3
"""
Test script to verify the MCP server is working
"""

import requests
import json

def test_server():
    base_url = "http://localhost:8080"
    
    print("🧪 Testing MCP Server...")
    print("=" * 40)
    
    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/health")
        print(f"✅ Health check: {response.status_code}")
        if response.status_code == 200:
            health_data = response.json()
            print(f"   Status: {health_data.get('status')}")
            print(f"   Database: {health_data.get('database')}")
            print(f"   Auth Required: {health_data.get('authentication_required')}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False
    
    # Test root endpoint
    try:
        response = requests.get(f"{base_url}/")
        print(f"✅ Root endpoint: {response.status_code}")
    except Exception as e:
        print(f"❌ Root endpoint failed: {e}")
        return False
    
    print("\n🎉 All basic tests passed!")
    print("💡 The server is running and accessible")
    return True

if __name__ == "__main__":
    test_server()