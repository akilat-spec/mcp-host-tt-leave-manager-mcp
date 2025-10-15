import secrets
import string

def generate_api_key(length=32):
    """Generate a secure random API key"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_multiple_keys(count=2):
    """Generate multiple API keys"""
    keys = [generate_api_key() for _ in range(count)]
    return keys

if __name__ == "__main__":
    print("🔐 Generating Secure API Keys...")
    print("=" * 50)
    
    keys = generate_multiple_keys(2)
    
    print("Primary Key (for production):")
    print(f"MCP_API_KEYS={keys[0]}")
    print()
    
    print("Backup Key:")
    print(f"MCP_API_KEYS={keys[0]},{keys[1]}")
    print()
    
    print("Individual keys:")
    for i, key in enumerate(keys, 1):
        print(f"Key {i}: {key}")
    
    print("=" * 50)
    print("📝 Copy the comma-separated keys to your .env file")