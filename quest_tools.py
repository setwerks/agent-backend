import os
import json
import logging
import requests
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from vertex_client import get_vertex_chat_response
from quest_prompts import FOR_SALE_PROMPT, HOUSING_PROMPT, JOBS_PROMPT, SERVICES_PROMPT, COMMUNITY_PROMPT, GIGS_PROMPT

# === SUPABASE CONFIG ===
SUPABASE_API = os.getenv("SUPABASE_API")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE")

# Local storage for development/testing
LOCAL_SESSIONS: Dict[str, Dict[str, Any]] = {}

# === TAXONOMY LOADED FROM EXTERNAL FILE ===
with open("taxonomy.json", "r") as f:
    TAXONOMY = json.load(f)

# === SESSION MANAGEMENT TOOLS USING SUPABASE ===
async def load_session(session_id: str) -> Dict[str, Any]:
    """Load session data from Supabase or local storage."""
    if not SUPABASE_API or not SUPABASE_KEY:
        # Use local storage if Supabase is not configured
        return LOCAL_SESSIONS.get(session_id, {
            "quest_state": {},
            "chat_history": []
        })
    
    try:
        response = requests.get(
            f"{SUPABASE_API}/quest_sessions?id=eq.{session_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }
        )
        if response.status_code == 200 and response.json():
            return response.json()[0]
    except Exception as e:
        logging.error(f"Error loading session from Supabase: {e}")
    
    return {
        "quest_state": {},
        "chat_history": []
    }

async def save_session(session_id: str, quest_state: Dict[str, Any], chat_history: List[Dict[str, str]]) -> None:
    """Save session data to Supabase or local storage."""
    if not SUPABASE_API or not SUPABASE_KEY:
        # Use local storage if Supabase is not configured
        LOCAL_SESSIONS[session_id] = {
            "quest_state": quest_state,
            "chat_history": chat_history
        }
        return
    
    try:
        data = {
            "id": session_id,
            "quest_state": quest_state,
            "chat_history": chat_history,
            "updated_at": "now()"
        }
        requests.post(
            f"{SUPABASE_API}/quest_sessions",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            },
            json=data
        )
    except Exception as e:
        logging.error(f"Error saving session to Supabase: {e}")
        # Fallback to local storage
        LOCAL_SESSIONS[session_id] = {
            "quest_state": quest_state,
            "chat_history": chat_history
        }

async def update_quest_state(session_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update quest state in Supabase."""
    current = await load_session(session_id)
    current["quest_state"].update(updates)
    await save_session(session_id, current["quest_state"], current["chat_history"])
    return current["quest_state"]

def safe_json_parse(response: str) -> dict:
    # Look for ###JSON### block
    match = re.search(r"###JSON###\s*({.*?})", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception as e:
            logging.error(f"Failed to parse JSON from ###JSON### block: {e} | {match.group(1)}")
    # Fallback: remove markdown/code block, try to parse first JSON object
    cleaned = re.sub(r"^```(?:json)?\s*|```$", "", response.strip(), flags=re.IGNORECASE | re.MULTILINE)
    try:
        return json.loads(cleaned)
    except Exception:
        # Try to extract any JSON object
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        logging.error(f"Failed to parse response as JSON: {response}")
        return {"text": response}

# === AI TOOLS ===
async def classify_quest(quest_text: str, taxonomy: Dict[str, Any] = TAXONOMY) -> Dict[str, Any]:
    """Classify quest using Vertex AI."""
    prompt = (
        f"You are a quest classifier. Given the following quest, output ONLY a valid JSON object with 'general_category' and 'sub_category' fields, and nothing else. "
        f"Here are the available general categories: {list(taxonomy.keys())}.\n"
        "Example output:\n"
        "```\n"
        "{\n"
        "  \"general_category\": \"for_sale\",\n"
        "  \"sub_category\": \"electronics\"\n"
        "}\n"
        "```\n"
        "Never include any explanation, comments, or text before or after the JSON. Only output the JSON object.\n"
        f"Quest: {quest_text}"
    )
    messages = [
            {"role": "user", "content": f"{prompt}\n{quest_text}"}
        ]
    response = get_vertex_chat_response(messages)
    return safe_json_parse(response)

async def geocode_location(location: str) -> Dict[str, Any]:
    """Geocode location using Vertex AI."""
    prompt = "You are a location geocoder. Given a location string, return a JSON object with 'latitude' and 'longitude' fields. If the location is ambiguous, return null for both fields."
    messages = [
        {"role": "user", "content": f"{prompt}\n{location}"}
    ]
    response = get_vertex_chat_response(messages)
    return safe_json_parse(response)

async def confirm_location(location: str, coordinates: Dict[str, float]) -> bool:
    """Confirm location using Vertex AI."""
    prompt = "You are a location confirmation system. Given a location string and coordinates, confirm if they match. Return a JSON object with a 'confirmed' boolean field."
    messages = [
        {"role": "user", "content": f"{prompt}\nLocation: {location}\nCoordinates: {coordinates}"}
    ]
    response = get_vertex_chat_response(messages)
    result = safe_json_parse(response)
    return result.get("confirmed", False)

# === QUEST PROCESSING ===
async def process_quest(
    quest_text: str,
    session_id: str,
    chat_history: List[Dict[str, str]]
) -> Dict[str, Any]:
    """Process a quest using Vertex AI."""
    # Classify quest
    classification = await classify_quest(quest_text)
    
    # Get category-specific prompt
    category = classification.get("general_category", "generic")
    prompt = get_category_prompt(category)
    
    # Process with category-specific prompt
    messages = [
        {"role": "user", "content": prompt},
        *chat_history,
        {"role": "user", "content": quest_text}
    ]
    response = get_vertex_chat_response(messages)
    result = safe_json_parse(response)
    
    # Update state
    await update_quest_state(session_id, {
        **classification,
        **result
    })
    
    return result

def get_category_prompt(category: str) -> str:
    """Get the prompt template for a specific category."""
    prompts = {
        "for_sale": FOR_SALE_PROMPT,
        "housing": HOUSING_PROMPT,
        "jobs": JOBS_PROMPT,
        "services": SERVICES_PROMPT,
        "community": COMMUNITY_PROMPT,
        "gigs": GIGS_PROMPT
    }
    return prompts.get(category, "You are a generic quest processor. Process the following quest:")
