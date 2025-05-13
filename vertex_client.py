import os
import logging
from typing import List, Dict, Any
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
        response_chunks = client.models.generate_content_stream(
            model=model_id,
            contents=contents,
            config=config,
        )
        # Collect all chunk.text, skipping None values
        texts = [str(chunk.text) for chunk in response_chunks if getattr(chunk, "text", None)]
        full_response = "".join(texts)
        print(f"Gemini response: {full_response}")
        return full_response
    except Exception as e:
        logging.error(f"Error in get_vertex_chat_response: {e}")
        raise