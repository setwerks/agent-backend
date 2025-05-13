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

def clean_json_response(text: str) -> str:
    """
    Clean up the response text by:
    1. Removing code fences and tags
    2. Finding the largest valid JSON block
    3. Fixing common JSON formatting issues
    """
    # Remove code fences and tags
    text = re.sub(r'```(?:json)?|###JSON###', '', text, flags=re.IGNORECASE).strip()
    
    # Find all potential JSON blocks using a simpler pattern
    # This looks for content between curly braces, handling nested braces
    json_blocks = []
    stack = []
    start = -1
    
    for i, char in enumerate(text):
        if char == '{':
            if not stack:  # Start of a new block
                start = i
            stack.append(char)
        elif char == '}':
            if stack:
                stack.pop()
                if not stack and start != -1:  # End of a complete block
                    json_blocks.append(text[start:i+1])
                    start = -1
    
    # Try each block from largest to smallest
    for block in sorted(json_blocks, key=len, reverse=True):
        try:
            # Try to parse as is
            json.loads(block)
            return block
        except json.JSONDecodeError:
            # Try to fix common issues
            try:
                # Remove trailing commas
                fixed = re.sub(r',\s*}', '}', block)
                fixed = re.sub(r',\s*]', ']', fixed)
                # Fix missing quotes around keys
                fixed = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', fixed)
                json.loads(fixed)
                return fixed
            except json.JSONDecodeError:
                continue
    
    # If no valid JSON found, return the original text
    return text

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
        # Get streaming response
        response_chunks = client.models.generate_content_stream(
            model=model_id,
            contents=contents,
            config=config,
        )
        
        # Buffer all chunks
        chunks = []
        for chunk in response_chunks:
            if hasattr(chunk, "text") and chunk.text:
                chunks.append(str(chunk.text))
        
        # Join all chunks
        raw_response = "".join(chunks)
        logging.info(f"Raw Gemini response: {raw_response}")
        
        # Clean and parse JSON
        cleaned_response = clean_json_response(raw_response)
        logging.info(f"Cleaned response: {cleaned_response}")
        
        return cleaned_response
    except Exception as e:
        logging.error(f"Error in get_vertex_chat_response: {e}")
        raise