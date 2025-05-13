from google.cloud import aiplatform
from dotenv import load_dotenv
import os

def list_models():
    # Load environment variables
    load_dotenv(override=True)
    
    # Initialize Vertex AI
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    region = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
    
    print(f"Initializing Vertex AI with project {project_id} in region {region}")
    aiplatform.init(project=project_id, location=region)
    
    # List available models
    print("\nListing available models:")
    try:
        models = aiplatform.Model.list()
        for model in models:
            print(f"Model: {model.name}")
            print(f"Display name: {model.display_name}")
            print(f"Description: {model.description}")
            print("---")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_models() 