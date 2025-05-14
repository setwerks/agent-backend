import os
import json
import logging
import requests
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from vertex_client import get_vertex_chat_response
from quest_prompts import FOR_SALE_PROMPT, HOUSING_PROMPT, JOBS_PROMPT, SERVICES_PROMPT, COMMUNITY_PROMPT, GIGS_PROMPT
import httpx

# === SUPABASE CONFIG ===
SUPABASE_API = os.getenv("SUPABASE_API")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Local storage for development/testing
LOCAL_SESSIONS: Dict[str, Dict[str, Any]] = {}

# === TAXONOMY LOADED FROM EXTERNAL FILE ===
with open("taxonomy.json", "r") as f:
    TAXONOMY = json.load(f)

# === SESSION MANAGEMENT TOOLS USING SUPABASE ===
async def load_session(session_id: str) -> Dict[str, Any]:
    logging.info(f"[load_session] Loading session: {session_id}")
    if not SUPABASE_API or not SUPABASE_KEY:
        session = LOCAL_SESSIONS.get(session_id, {
            "quest_state": {},
            "chat_history": []
        })
        logging.info(f"[load_session] Loaded from LOCAL_SESSIONS: {session}")
        logging.info(f"[load_session] Loaded quest_state: {session.get('quest_state', {})}")
        return session
    try:
        response = requests.get(
            f"{SUPABASE_API}/rest/v1/quest_sessions?quest_id=eq.{session_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }
        )
        logging.info(f"[load_session] Supabase GET status: {response.status_code}, response: {response.text}")
        if response.status_code == 200 and response.json():
            session = response.json()[0]
            logging.info(f"[load_session] Loaded session from Supabase: {session}")
            logging.info(f"[load_session] Loaded quest_state: {session.get('quest_state', {})}")
            return session
        else:
            logging.info(f"[load_session] No session found in Supabase for: {session_id}")
    except Exception as e:
        logging.error(f"[load_session] Error loading session from Supabase: {e}")
    return {
        "quest_state": {},
        "chat_history": []
    }

async def save_session(session_id: str, quest_state: Dict[str, Any], chat_history: List[Dict[str, str]]) -> None:
    logging.info(f"[save_session] Saving session: {session_id} with quest_state: {quest_state} and chat_history: {chat_history}")
    if not SUPABASE_API or not SUPABASE_KEY:
        LOCAL_SESSIONS[session_id] = {
            "quest_state": quest_state,
            "chat_history": chat_history
        }
        logging.info(f"[save_session] Saved to LOCAL_SESSIONS: {LOCAL_SESSIONS[session_id]}")
        return
    try:
        data = {
            "quest_id": session_id,
            "quest_state": quest_state,
            "chat_history": chat_history,
            "last_updated": "now()"
        }
        response = requests.post(
            f"{SUPABASE_API}/rest/v1/quest_sessions",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            },
            json=data
        )
        logging.info(f"[save_session] Supabase POST status: {response.status_code}, response: {response.text}")
    except Exception as e:
        logging.error(f"[save_session] Error saving session to Supabase: {e}")
        # Fallback to local storage
        LOCAL_SESSIONS[session_id] = {
            "quest_state": quest_state,
            "chat_history": chat_history
        }
        logging.info(f"[save_session] Fallback saved to LOCAL_SESSIONS: {LOCAL_SESSIONS[session_id]}")

async def update_quest_state(session_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update quest state in Supabase."""
    current = await load_session(session_id)
    logging.info(f"[update_quest_state] Current quest_state: {current['quest_state']}")
    current["quest_state"].update(updates)
    logging.info(f"[update_quest_state] Updated quest_state: {current['quest_state']}")
    await save_session(session_id, current["quest_state"], current["chat_history"])
    return current["quest_state"]

def safe_json_parse(response: str) -> dict:
    import re
    import json
    logging.info(f"Safe JSON Response: {response}")
    
    # Try to find JSON blocks with triple backticks first
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
    if code_block_match:
        try:
            json_str = code_block_match.group(1)
            logging.info(f"Found JSON in code block: {json_str}")
            return json.loads(json_str)
        except Exception as e:
            logging.error(f"Failed to parse JSON from code block: {e}")
    
    # Try to find JSON blocks with ###JSON### marker
    json_marker_match = re.search(r'###JSON###\s*(\{.*?\})', response, re.DOTALL)
    if json_marker_match:
        try:
            json_str = json_marker_match.group(1)
            logging.info(f"Found JSON with marker: {json_str}")
            return json.loads(json_str)
        except Exception as e:
            logging.error(f"Failed to parse JSON with marker: {e}")
    
    # Find all JSON objects in the response
    matches = re.findall(r'({[^{}]+(?:{[^{}]*}[^{}]*)*})', response, re.DOTALL)
    if matches:
        # Try the largest one first
        matches = sorted(matches, key=len, reverse=True)
        for m in matches:
            try:
                logging.info(f"Trying to parse JSON block: {m}")
                return json.loads(m)
            except Exception as e:
                logging.error(f"Failed to parse JSON block: {e} | {m}")
    
    logging.error(f"Failed to extract JSON, returning empty dict. Response: {response}")
    return {}

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
    """Geocode location using our /api/geocode endpoint."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{settings.API_BASE_URL}/api/geocode",
                params={"location": location}
            )
            response.raise_for_status()
            data = response.json()
            return {
                "latitude": data.get("lat"),
                "longitude": data.get("lng")
            }
        except Exception as e:
            logger.error(f"Geocoding failed for location '{location}': {str(e)}")
            return {"latitude": None, "longitude": None}

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
    # Load current quest state from session
    session = await load_session(session_id)
    current_quest_state = session.get("quest_state", {})
    logging.info(f"[process_quest] Loaded current quest_state: {current_quest_state}")

    # Only classify if general_category/sub_category are missing
    if not (current_quest_state.get("general_category") and current_quest_state.get("sub_category")):
        logging.info(f"[process_quest] Running classify_quest for: {quest_text}")
        classification = await classify_quest(quest_text)
        logging.info(f"Classification result: {classification}")
        
        # Update quest_sessions with category info
        try:
            session_update = {
                "general_category": classification.get("general_category"),
                "sub_category": classification.get("sub_category"),
                "last_updated": "now()"
            }
            response = requests.patch(
                f"{SUPABASE_API}/rest/v1/quest_sessions?quest_id=eq.{session_id}",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                json=session_update
            )
            if response.status_code not in (200, 201):
                logging.error(f"Failed to update quest_sessions with category info: {response.text}")
        except Exception as e:
            logging.error(f"Error updating quest_sessions with category info: {str(e)}")
        
        # Update current quest state with classification
        current_quest_state.update(classification)
    else:
        classification = {
            "general_category": current_quest_state.get("general_category"),
            "sub_category": current_quest_state.get("sub_category")
        }
        logging.info(f"[process_quest] Using existing classification: {classification}")

    # Get category-specific prompt
    category = classification.get("general_category", "generic")
    prompt = get_category_prompt(category)
    logging.info(f"Using category: {category}")

    # Build messages: system message with current quest state, then prompt, then chat history, then user message
    system_message = {"role": "user", "content": f"Current quest state: {json.dumps(current_quest_state)}"}
    messages = [
        system_message,
        {"role": "user", "content": prompt},
        *chat_history,
        {"role": "user", "content": quest_text}
    ]
    logging.info(f"Sending messages to Vertex AI: {messages}")
    response = get_vertex_chat_response(messages)
    logging.info(f"Raw Vertex AI response: {response}")
    result = safe_json_parse(response)
    logging.info(f"Parsed result: {result}")

    # Update state
    state_update = {
        **classification,
        **result
    }
    logging.info(f"Updating quest state with: {state_update}")
    await update_quest_state(session_id, state_update)

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
