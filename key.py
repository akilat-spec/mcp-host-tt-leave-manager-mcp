import secrets
import string

# Generate a secure random API key (32 characters)
def generate_api_key(length=32):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

# Generate multiple keys
key1 = generate_api_key()
key2 = generate_api_key()

print(f"MCP_API_KEYS={key1},{key2}")