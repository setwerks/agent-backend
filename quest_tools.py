import os
import json
import logging
import requests
from datetime import datetime
from typing import Dict, Any, List

from pydantic import BaseModel
from agents import function_tool, RunContextWrapper

# Supabase config
SUPABASE_API    = os.getenv("SUPABASE_API")
SUPABASE_KEY    = os.getenv("SUPABASE_SERVICE_ROLE")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}
try:
    taxonomy_path = os.getenv("TAXONOMY_PATH", "taxonomy.json")
    with open(taxonomy_path, "r") as tf:
        TAXONOMY = json.load(tf)
except Exception as e:
    logging.error("Failed to load taxonomy from %s: %s", taxonomy_path, e)
    TAXONOMY = {}

# --- Pydantic models for strict schemas ---
class SessionData(BaseModel):
    quest_state: Dict[str, Any]
    chat_history: List[Any]
    class Config:
        extra = "forbid"

class SessionSaveResponse(BaseModel):
    session_id: str
    class Config:
        extra = "forbid"

class UpdateResponse(BaseModel):
    message: str
    class Config:
        extra = "forbid"

class Classification(BaseModel):
    general_category: str
    sub_category: str
    class Config:
        extra = "forbid"

class ConfirmLocationResponse(BaseModel):
    message: str
    class Config:
        extra = "forbid"

class GeocodeLocationResponse(BaseModel):
    message: str
    class Config:
        extra = "forbid"

# === SESSION MANAGEMENT TOOLS ===
@function_tool
async def load_session(session_id: str) -> SessionData:
    url = f"{SUPABASE_API}?quest_id=eq.{session_id}"
    res = requests.get(url, headers=SUPABASE_HEADERS)
    if res.status_code != 200:
        logging.error("Supabase load_session error: %s %s", res.status_code, res.text)
        return SessionData(quest_state={}, chat_history=[])
    data = res.json()
    if not data:
        logging.info("Creating new session for session_id: %s", session_id)
        init_payload = {
            "quest_id": session_id,
            "quest_state": {},
            "chat_history": [],
            "last_updated": datetime.utcnow().isoformat()
        }
        create = requests.post(SUPABASE_API, headers=SUPABASE_HEADERS, json=init_payload)
        create.raise_for_status()
        return SessionData(quest_state={}, chat_history=[])
    record = data[0]
    return SessionData(
        quest_state=record.get("quest_state", {}),
        chat_history=record.get("chat_history", [])
    )

@function_tool
async def save_session(session_id: str, quest_state: Dict[str, Any], chat_history: List[Any]) -> SessionSaveResponse:
    state_copy = quest_state.copy()
    state_copy.pop("ui", None)
    payload = {
        "quest_id": session_id,
        "quest_state": state_copy,
        "chat_history": chat_history,
        "last_updated": datetime.utcnow().isoformat()
    }
    url = f"{SUPABASE_API}?quest_id=eq.{session_id}"
    res = requests.patch(url, headers=SUPABASE_HEADERS, json=payload)
    res.raise_for_status()
    return SessionSaveResponse(session_id=session_id)

@function_tool
def update_quest_state(ctx: RunContextWrapper, field: str, value: Any) -> UpdateResponse:
    ctx.context.quest_state[field] = value
    logging.info("[update_quest_state] Set %s = %s", field, value)
    return UpdateResponse(message=f"Saved `{field}`.")

# === CLASSIFICATION TOOL ===
@function_tool
async def classify_quest(text: str) -> Classification:
    prompt = (
        "You are a classification assistant. Given a user query and a taxonomy of Craigslist-style categories, "
        "choose exactly one general_category and one sub_category from the taxonomy. "
        "Do NOT invent new categories or subcategories. "
        "Respond ONLY with a JSON object with keys 'general_category' and 'sub_category'.\n\n"
        f"Taxonomy: {json.dumps(TAXONOMY)}\n"
        f"User request: \"{text}\""
    )
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "system", "content": prompt}],
            "temperature": 0
        }
    )
    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content)
        return Classification(**parsed)
    except Exception as e:
        logging.error("Classification parse error: %s — %s", e, data)
        return Classification(general_category="general", sub_category="")

# === LOCATION TOOLS ===
@function_tool
def confirm_location(ctx: RunContextWrapper) -> ConfirmLocationResponse:
    ctx.context.quest_state["location_confirmed"] = True
    logging.info("[confirm_location] Set location_confirmed = True")
    return ConfirmLocationResponse(message="✅ Location confirmed.")

@function_tool
async def geocode_location(ctx: RunContextWrapper, location: str) -> GeocodeLocationResponse:
    logging.info("[geocode_location] Tool called")
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location, "format": "json", "limit": 1}
    headers = {"User-Agent": "Questor-Agent/1.0"}
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return GeocodeLocationResponse(message=f"Error fetching location data: {str(e)}")
    if not data:
        return GeocodeLocationResponse(message=f"Sorry, I couldn't find '{location}'.")
    result = data[0]
    lat = result["lat"]
    lon = result["lon"]
    map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
    ctx.context.quest_state["general_location"] = location
    ctx.context.quest_state["location_confirmed"] = False
    ctx.context.quest_state["geocoded_location"] = {"input": location, "lat": lat, "lon": lon, "map_url": map_url}
    logging.info("[geocode_location] Updated quest_state: %s", json.dumps(ctx.context.quest_state))
    json_output = {
        "general_location": location,
        "location_confirmed": False,
        "geocoded_location": {"input": location, "lat": lat, "lon": lon, "map_url": map_url},
        "action": "validate_location",
        "ui": {"trigger": "location_confirm", "buttons": ["Yes", "No"]}
    }
    body = (
        f"I found a location match for '{location}': [View on Map]({map_url})\n"
        "Is this the correct location?\n\n###JSON###\n"
        f"{json.dumps(json_output, indent=2)}"
    )
    return GeocodeLocationResponse(message=body)
