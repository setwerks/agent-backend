import os
import json
import logging
import requests
import uvicorn
import re
from datetime import datetime
from uuid import uuid4
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List
from agents import Agent, Runner, function_tool, RunConfig, RunContextWrapper, enable_verbose_stdout_logging
from dataclasses import dataclass
import tiktoken
import copy
import time

def estimate_token_usage(messages: list, model: str = "gpt-4o") -> int:
    encoding = tiktoken.encoding_for_model(model)
    tokens = 0

    for message in messages:
        # Rough estimate of message structure
        tokens += 4  # every message has base structure
        for key, value in message.items():
            tokens += len(encoding.encode(str(value)))
    tokens += 2  # every reply is primed with <|start|>assistant
    return tokens

#enable_verbose_stdout_logging()
@dataclass
class QuestContext:
    quest_state: dict

# Load environment variables
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Supabase config
SUPABASE_API = os.getenv("SUPABASE_API")  # e.g., https://xyz.supabase.co/rest/v1/quest_sessions
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def build_dynamic_prompt(quest_state, history):
    action = quest_state.get("action")
    description = quest_state.get("description")
    location = quest_state.get("general_location")
    price = quest_state.get("price")
    distance = quest_state.get("distance")
    distance_unit = quest_state.get("distance_unit")
    want_or_have = quest_state.get("want_or_have")
    location_confirmed = quest_state.get("location_confirmed")

    if action == "ask_for_price":
        return (
            f"You are helping a user set a price for their quest.\n"
            f"Current description: {description}\n"
            f"Current location: {location}\n"
            f"Ask the user for their price or budget."
        )
    elif action == "offer_photos":
        return (
            f"You are helping a user upload photos for their quest.\n"
            f"Current description: {description}\n"
            f"Ask if they want to upload photos."
        )
    elif action == "ask_for_distance":
        return (
            f"You are helping a user set a search distance for their quest.\n"
            f"Current description: {description}\n"
            f"Current location: {location}\n"
            f"Ask how far they are willing to look ({distance_unit})."
        )
    elif action == "validate_location" and location_confirmed is False:
        return (
            f"You are helping a user confirm their location for a quest.\n"
            f"Current location: {location}\n"
            f"Ask the user to confirm or correct their location."
        )
    elif action == "validate_location" and location_confirmed is True:
        return (
            f"You are helping a user confirm their location for a quest.\n"
            f"Current location: {location}\n"
            f"The location is confirmed, so ask the user to post the quest."
        )# Add more action-specific prompts as needed

    # Fallback to the full prompt
    return quest_prompt

os.makedirs("uploads", exist_ok=True)
app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

# Default quest state template
DEFAULT_QUEST_STATE = {
    "want_or_have": None,
    "description": None,
    "general_location": None,
    "location_confirmed": False,
    "distance": None,
    "distance_unit": "mi",
    "price": None,
    "photos": [],
    "action": None,
    "ui": None,
}

def ensure_full_quest_state(state):
    full_state = copy.deepcopy(DEFAULT_QUEST_STATE)
    if state:
        full_state.update(state)
    return full_state

@function_tool
def confirm_location(ctx: RunContextWrapper[QuestContext]) -> str:
    ctx.context.quest_state["location_confirmed"] = True
    logging.info("[confirm_location] Set location_confirmed = True")
    return "✅ Location confirmed."

@function_tool
def update_quest_state(ctx: RunContextWrapper[QuestContext], field: str, value: str) -> str:
    ctx.context.quest_state[field] = value
    logging.info("[update_quest_state] Set %s = %s", field, value)
    return f"Saved `{field}`."

# === TOOL 1: Geocode location ===
@function_tool
async def geocode_location(ctx: RunContextWrapper[QuestContext], location: str) -> str:
    logging.info("[geocode_location] Tool called")
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: Google Maps API key is missing. Please set GOOGLE_MAPS_API_KEY in your environment."

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": location, "key": api_key}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"Error fetching location data: {str(e)}"

    if data.get("status") == "REQUEST_DENIED":
        return "Error: Google Maps API request was denied. Please check your API key and enable the Geocoding API."
    if data.get("status") == "ZERO_RESULTS":
        return f"No results found for location: '{location}'. Please try a more specific address."
    if data.get("status") != "OK" or not data.get("results"):
        return f"Geocoding failed with status: {data.get('status')}"

    result = data["results"][0]
    lat = result["geometry"]["location"]["lat"]
    lon = result["geometry"]["location"]["lng"]

    city = ""
    state = ""
    for component in result["address_components"]:
        if "locality" in component["types"]:
            city = component["long_name"]
        elif "administrative_area_level_1" in component["types"]:
            state = component["long_name"]

    if not city or not state:
        return "Could not find city and state information in the geocoding result."

    formatted_address = f"{city}, {state}"
    map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
    # Google Static Maps image
    static_map_url = (
        f"https://maps.googleapis.com/maps/api/staticmap"
        f"?center={lat},{lon}&zoom=12&size=600x300&markers=color:red%7C{lat},{lon}&key={api_key}"
    )

    # ✅ Update quest_state (but DO NOT confirm yet)
    ctx.context.quest_state["general_location"] = formatted_address
    ctx.context.quest_state["location_confirmed"] = False  # wait for user confirmation
    ctx.context.quest_state["geocoded_location"] = {
        "input": location,
        "lat": lat,
        "lon": lon,
        "map_url": map_url,
        "static_map_url": static_map_url,
        "formatted_address": formatted_address,
    }

    logging.info("[geocode_location] Updated quest_state: %s", json.dumps(ctx.context.quest_state))

    json_output = {
        "general_location": formatted_address,
        "location_confirmed": False,
        "geocoded_location": {
            "input": location,
            "lat": lat,
            "lon": lon,
            "map_url": map_url,
            "static_map_url": static_map_url,
            "formatted_address": formatted_address,
        },
        "action": "validate_location",
        "ui": {
            "trigger": "location_confirm",
            "buttons": ["Yes", "No"]
        }
    }

    return (
        f"I found a location match for '{location}': [View on Map]({map_url})\n"
        f"![Map Image]({static_map_url})\n"
        f"Is this the correct location?\n\n###JSON###\n{json.dumps(json_output, indent=2)}"
    )
# === TOOL 2: Create quest ===
class QuestData(BaseModel):
    want_or_have: Optional[str] = None
    description: Optional[str] = None
    general_location: Optional[str] = None
    location_confirmed: Optional[bool] = None
    distance: Optional[float] = None
    distance_unit: Optional[str] = None
    price: Optional[float] = None
    photos: Optional[List[str]] = None  # ✅ fixed: no default list

    model_config = {
        'extra': 'forbid'  # ✅ preserves strict schema
    }

@function_tool
def create_quest(quest_data: QuestData) -> str:
    logging.info("[create_quest] Tool called")
    try:
        api_url = os.getenv("QUEST_CREATE_ENDPOINT", "http://localhost:5000/quests")
        response = requests.post(api_url, json=quest_data.dict())
        response.raise_for_status()
        return "✅ Quest has been created!"
    except Exception as e:
        return f"❌ Failed to create quest: {str(e)}"

# === SESSION HELPERS ===
def load_session(quest_id: str):
    url = f"{SUPABASE_API}?quest_id=eq.{quest_id}"
    res = requests.get(url, headers=SUPABASE_HEADERS)
    
    if res.status_code == 404 or not res.json():
        # Session not found — create it
        logging.info("Creating new session for quest_id: %s", quest_id)
        init_payload = {
            "quest_id": quest_id,
            "quest_state": {},
            "chat_history": [],
            "last_updated": datetime.utcnow().isoformat()
        }
        create_res = requests.post(SUPABASE_API, headers=SUPABASE_HEADERS, json=init_payload)
        create_res.raise_for_status()
        return init_payload
    
    res.raise_for_status()
    data = res.json()
    return data[0]

def save_session(quest_id: str, quest_state: dict, chat_history: list):
    # Create a copy of quest_state and remove UI
    quest_state_copy = quest_state.copy()
    quest_state_copy.pop('ui', None)
        
    payload = {
        "quest_id": quest_id,
        "quest_state": quest_state_copy,
        "chat_history": chat_history,
        "last_updated": datetime.utcnow().isoformat()
    }
    
    url = f"{SUPABASE_API}?quest_id=eq.{quest_id}"
    res = requests.patch(url, headers=SUPABASE_HEADERS, json=payload)
    res.raise_for_status()
    # Don't try to parse response as JSON since PATCH doesn't return any

# === AGENT PROMPT ===
quest_prompt = """You are a helpful onboarding assistant for a quest app. You help users create a new quest by collecting the following information, step by step:

What the user wants or has (e.g., "offering a new car")  
A short description  
The general location (city, state)  
Confirmation of the location  
The distance (in km or miles) for the quest  
Price, if applicable (see rules below)

Price Handling Rules  
If the quest is about a tangible item (e.g., a car, bike, laptop, etc.):  
If the user has something to offer (e.g., "I have an old car I want to sell"), ask for the price they want to sell it for.  
Example: "How much would you like to sell your car for?"  
If the user wants something (e.g., "I want to buy a car"), ask how much they are willing to pay.  
Example: "What is your budget or how much are you willing to pay?"  
If the quest is for a service, experience, or non-tangible (e.g., "want someone to ride bikes with"), do not ask for price.  
Use your best judgment based on the description and context. If unsure, do not ask for price.

General Instructions  
If the user's message includes what they are offering or seeking (e.g., "offering a new car in oakland,ca"), extract the description (e.g., "a new car") and use it for the description field.  
Only ask for a description if you cannot infer it from the user's input.  
If you are unsure, use a reasonable default like "a new car" or echo the item/quest mentioned by the user.  
Do not ask for the description again if you already have one.  
Only ask for location confirmation if location_confirmed is not true.  
Only ask for distance if it is missing.  
Only offer the photo upload once, after all required fields are present.  
When all fields are present and confirmed, and the photo step is complete (either photos provided or skipped), set action: "ready".  
Always include the latest values for all fields in the JSON.  
Never ask for the same information twice unless the user says it was incorrect.  
Confirmation of the location uses geocode_location tool but if there is any question prompt the user to post the location again.  
When the action field is "ready", prompt the user to post the quest with UI Example: "ui": {
  "trigger": "post_quest",
  "buttons": ["Yes", "No"]
}

User Interface Hints (for frontend rendering)  
When asking a question that can benefit from a UI element (e.g., yes/no buttons, location confirmation, distance choices), include a `"ui"` field inside the JSON block.

- `ui.trigger`: A string that indicates the frontend UI component to show (e.g., "yes_no", "location_confirm", "distance_select", "map_confirm").  
- `ui.buttons`: Optional. A list of strings representing quick-reply buttons (e.g., ["Yes", "No"], ["5 mi", "10 mi", "20 mi"]).  
- Do not use HTML. The frontend handles rendering based on the `ui` metadata.  
- You must still include all the usual fields (like want_or_have, description, etc.) as part of the complete quest state.  
- Only include the `"ui"` field when a visual component would enhance the user experience. If not needed, omit the `ui` field entirely.

JSON Output  
ALWAYS output a JSON block at the end of your message, delimited by ###JSON###, containing the current state and an action field. The action field must be one of:  
"validate_location"  
"ask_for_distance"  
"ask_for_price"  
"offer_photos"  
"ready"  
"summarize"

When you output JSON, it must be valid JSON:  
> - Do not include comments.  
> - All property names and string values must be double-quoted.  
> - Do not include trailing commas.

Examples:

How much would you like to sell your car for?  
###JSON###  
{
  "want_or_have": "have",
  "description": "an old car",
  "general_location": "Oakland, CA",
  "location_confirmed": true,
  "distance": 8,
  "distance_unit": "km",
  "price": null,
  "action": "ask_for_price"
}

Would you like to upload any photos for your quest?  
###JSON###  
{
  "want_or_have": "have",
  "description": "an old car",
  "general_location": "Oakland, CA",
  "location_confirmed": true,
  "distance": 8,
  "distance_unit": "km",
  "price": 5000,
  "photos": [],
  "action": "offer_photos"
}

Is this your correct location?  
###JSON###  
{
  "want_or_have": "have",
  "description": "a used bike",
  "general_location": "Oakland, CA",
  "location_confirmed": false,
  "distance": null,
  "distance_unit": "mi",
  "price": null,
  "photos": [],
  "action": "validate_location",
  "ui": {
    "trigger": "location_confirm",
    "buttons": ["Yes", "No"]
  }
}

How far are you willing to look?  
###JSON###  
{
  "want_or_have": "want",
  "description": "a new car",
  "general_location": "San Francisco, CA",
  "location_confirmed": true,
  "distance": null,
  "distance_unit": "mi",
  "price": null,
  "photos": [],
  "action": "ask_for_distance",
  "ui": {
    "trigger": "distance_select",
    "buttons": ["5 mi", "10 mi", "20 mi"]
  }
}
"""

quest_agent = Agent(
    name="quest-onboarding-agent-2",
    instructions=quest_prompt,
    tools=[geocode_location, create_quest, update_quest_state, confirm_location],
    model="gpt-4o",
)

# === FALLBACK AGENT ===
fallback_prompt = """You are a helpful assistant that generates appropriate messages based on the quest state and history.
Your task is to generate a single message that:
1. Acknowledges the user's last input
2. Asks for the next required information based on the quest state
3. Is conversational and natural

Current quest state:
{quest_state}

Last few messages:
{history}

Generate a single message that continues the conversation naturally."""

fallback_agent = Agent(
    name="quest-fallback-agent",
    instructions=fallback_prompt,
    model="gpt-4o",
)

# === MAIN QUEST ROUTE ===
@app.post("/start-quest")
async def start_quest(request: Request):
    t0 = time.time()
    try:
        body = await request.json()
        message = body.get("message")
        quest_id = body.get("quest_id")

        if not message or not quest_id:
            return {"error": "Missing 'message' or 'quest_id'"}

        session = load_session(quest_id)
        t1 = time.time()
        history = session.get("chat_history", [])
        quest_state = session.get("quest_state", {})

        # Always start with a full quest state
        quest_state = ensure_full_quest_state(quest_state)

        input_items = [
            {"role": m["role"], "content": m["content"]}
            for m in history if "role" in m and "content" in m
        ] + [{"role": "user", "content": message}]

        # Use structured context object so quest_state is mutable
        context = QuestContext(quest_state=quest_state)

        dynamic_prompt = build_dynamic_prompt(quest_state, history)
        dynamic_agent = Agent(
            name="quest-onboarding-agent-2",
            instructions=dynamic_prompt,
            tools=[geocode_location, create_quest, update_quest_state, confirm_location],
            model="gpt-4o",
        )
        logging.info(f"Using dynamic prompt for action: {quest_state.get('action')}")
        result = await Runner.run(
            starting_agent=dynamic_agent,
            input=input_items,
            context=context,
            run_config=RunConfig(workflow_name="quest_workflow")
        )
        t2 = time.time()

        logging.info("Updated quest_state: %s", json.dumps(context.quest_state, indent=2))
        # Extract and store structured JSON block if present
        json_match = re.search(r"###JSON###\s*(\{.*\})", result.final_output, re.DOTALL)
        logging.info("JSON match: %s", json_match)
        if json_match:
            try:
                extracted = json.loads(json_match.group(1))
                context.quest_state.update(extracted)
                logging.info("[start-quest] Extracted quest_state update: %s", json.dumps(extracted))
                
                # Get the message part before the JSON
                message_part = result.final_output[:json_match.start()].strip()
                
                # If no explicit message, use fallback agent to generate one
                if not message_part:
                    # Get last 3 messages for context
                    recent_history = history[-3:] if len(history) > 3 else history
                    fallback_input = [
                        {"role": "system", "content": fallback_prompt.format(
                            quest_state=json.dumps(context.quest_state, indent=2),
                            history="\n".join([f"{m['role']}: {m['content']}" for m in recent_history])
                        )}
                    ]
                    fallback_result = await Runner.run(
                        starting_agent=fallback_agent,
                        input=fallback_input,
                        context=context,
                        run_config=RunConfig(workflow_name="fallback_workflow")
                    )
                    clean_output = fallback_result.final_output.strip()
                else:
                    clean_output = message_part
                    
            except json.JSONDecodeError as e:
                logging.warning("Could not parse JSON block from assistant output: %s", e)
                clean_output = result.final_output
        else:
            clean_output = result.final_output

        # Ensure all keys are present in quest_state before saving/returning
        context.quest_state = ensure_full_quest_state(context.quest_state)

        updated_history = input_items + [
            {"role": "assistant", "content": clean_output}
        ]

        save_session(quest_id, context.quest_state, updated_history)
        t3 = time.time()

        logging.info(f"TIMING: load_session={t1-t0:.2f}s, agent_run={t2-t1:.2f}s, save_session={t3-t2:.2f}s, total={t3-t0:.2f}s")

        token_estimate = estimate_token_usage(input_items)

        return {
                "message": clean_output,
                "quest_state": context.quest_state,  # optional: useful for frontend syncing
                "token_stats": token_estimate
                }

    except Exception as e:
        logging.exception("Quest agent failed")
        return {"error": str(e)}

# === PHOTO UPLOAD ===
@app.post("/upload-photo")
async def upload_photo(file: UploadFile = File(...)):
    try:
        os.makedirs("uploads", exist_ok=True)
        file_ext = file.filename.split(".")[-1]
        file_id = f"{uuid4()}.{file_ext}"
        file_path = os.path.join("uploads", file_id)

        with open(file_path, "wb") as f:
            f.write(await file.read())

        photo_url = f"/uploads/{file_id}"
        return {"url": photo_url}

    except Exception as e:
        logging.exception("Photo upload failed")
        return {"error": str(e)}

# === ENTRY POINT ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)