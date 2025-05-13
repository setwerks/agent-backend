from google.cloud import aiplatform
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

def check_model_availability():
    """Check if the Gemini model is available in the specified region."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    region = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    print(f"\nChecking Vertex AI configuration:")
    print(f"Project ID: {project_id}")
    print(f"Region: {region}")
    print(f"Credentials path: {credentials_path}")

    try:
        # Initialize Vertex AI
        aiplatform.init(project=project_id, location=region)
        print("\nSuccessfully initialized Vertex AI")

        # List available models
        print("\nFetching available models...")
        models = aiplatform.Model.list()
        
        print("\nAvailable models:")
        for model in models:
            print(f"- {model.display_name} ({model.name})")

        # Check specifically for Gemini
        gemini_model = f"projects/{project_id}/locations/{region}/publishers/google/models/gemini-1.5-pro"
        print(f"\nChecking for Gemini model: {gemini_model}")
        
        try:
            endpoint = aiplatform.Endpoint(gemini_model)
            print("✅ Gemini model is available!")
        except Exception as e:
            print(f"❌ Error accessing Gemini model: {str(e)}")
            print("\nTrying alternative models...")
            alternative_models = [
                "gemini-1.0-pro",
                "gemini-1.0-pro-vision",
                "text-bison@002",
                "chat-bison@002"
            ]
            for model in alternative_models:
                try:
                    test_model = f"projects/{project_id}/locations/{region}/publishers/google/models/{model}"
                    endpoint = aiplatform.Endpoint(test_model)
                    print(f"✅ {model} is available!")
                except Exception as e:
                    print(f"❌ {model} is not available: {str(e)}")

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")

if __name__ == "__main__":
    check_model_availability() 