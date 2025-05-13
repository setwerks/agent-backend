from dotenv import load_dotenv
from vertex_client import get_vertex_chat_response
import os

def test_chat():
    # Load environment variables
    load_dotenv(override=True)
    
    # Print configuration
    print("Configuration:")
    print(f"Project ID: {os.getenv('GOOGLE_CLOUD_PROJECT')}")
    print(f"Region: {os.getenv('GOOGLE_CLOUD_REGION')}")
    print(f"Credentials: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
    print(f"Model ID: {os.getenv('VERTEX_CHAT_MODEL_ID')}")
    
    # Test message
    messages = [
        {"role": "user", "content": "Hello, how are you?"}
    ]
    
    try:
        response = get_vertex_chat_response(messages)
        print("\nResponse:")
        print(response)
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    test_chat() 