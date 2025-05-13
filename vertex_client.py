import os
import logging
import re
import json
from typing import List, Dict, Any, Optional
from google import genai

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
REGION = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
CHAT_MODEL_ID = os.getenv("VERTEX_CHAT_MODEL_ID", "gemini-2.5-pro-preview-05-06")

# Initialize the genai client
client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=REGION,
)

def get_vertex_chat_response(
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1024,
    model_id: str = CHAT_MODEL_ID
) -> str:
    """
    Get chat completion from Vertex AI Gemini model using google-genai SDK.
    messages: List of {"role": ..., "content": ...}
    Returns the response text.
    """
    # Convert messages to genai.types.Content
    contents = [
        genai.types.Content(
            role=m["role"],
            parts=[genai.types.Part(text=m["content"])]
        ) for m in messages
    ]
    config = genai.types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    try:
        # Use non-streaming mode
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=config,
        )
        
        if not response.text:
            raise ValueError("Empty response from Gemini")
            
        # Basic cleanup - just remove code fences and tags
        text = str(response.text)
        text = re.sub(r'```(?:json)?|###JSON###', '', text, flags=re.IGNORECASE).strip()
        
        logging.info(f"Raw Gemini response: {text}")
        
        # Try to parse as JSON
        try:
            parsed = json.loads(text)
            return json.dumps(parsed)  # Return formatted JSON
        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error: {e}")
            return text  # Return original text if JSON parsing fails
            
    except Exception as e:
        logging.error(f"Error in get_vertex_chat_response: {e}")
        raise