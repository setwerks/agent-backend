import os
import json
import logging
import requests
import uvicorn
from datetime import datetime
from uuid import uuid4
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List
from agents import Agent, Runner, function_tool, RunConfig

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

os.makedirs("uploads", exist_ok=True)
app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

# === TOOL 1: Geocode location ===
@function_tool
def geocode_location(location: str) -> str:
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location, "format": "json", "limit": 1}
    headers = {"User-Agent": "Questor-Agent/1.0"}
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"Error fetching location data: {str(e)}"
    if not data:
        return f"Sorry, I couldn't find '{location}'."
    result = data[0]
    lat = result["lat"]
    lon = result["lon"]
    map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
    return f"{location} is at latitude {lat}, longitude {lon}. [View on Map]({map_url})"

# === TOOL 2: Create quest ===
class QuestData(BaseModel):
    want_or_have: Optional[str]
    description: Optional[str]
    general_location: Optional[str]
    location_confirmed: Optional[bool]
    distance: Optional[float]
    distance_unit: Optional[str]
    price: Optional[float]
    photos: Optional[List[str]] = []

    model_config = {
        'extra': 'forbid'
    }

@function_tool
def create_quest(quest_data: QuestData) -> str:
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
    payload = {
        "quest_state": quest_state,
        "chat_history": chat_history,
        "last_updated": datetime.utcnow().isoformat()
    }
    res = requests.patch(f"{SUPABASE_API}?quest_id=eq.{quest_id}", json=payload, headers=SUPABASE_HEADERS)
    res.raise_for_status()

# === AGENT PROMPT ===
quest_prompt = """
You are a helpful onboarding assistant for a quest app. You help users create a new quest by collecting the following information, step by step:
What the user wants or has (e.g., “offering a new car”)
A short description
The general location (city, state)
Confirmation of the location
The distance (in km or miles) for the quest
Price, if applicable
Photos (optional)
Use buttons for Yes/No confirmation prompts, or accept typed responses.
When all required fields are collected and confirmed, call create_quest with the data.
Never ask for the same information twice unless the user says it's incorrect.
"""

# === AGENT ===
quest_agent = Agent(
    name="quest-onboarding-agent",
    instructions=quest_prompt,
    tools=[geocode_location, create_quest],
    model="gpt-4o"
)

# === MAIN QUEST ROUTE ===
@app.post("/start-quest")
async def start_quest(request: Request):
    print(dir(Runner))
    try:
        body = await request.json()
        message = body.get("message")
        quest_id = body.get("quest_id")

        if not message or not quest_id:
            return {"error": "Missing 'message' or 'quest_id'"}

        session = load_session(quest_id)
        history = session.get("chat_history", [])

        result = await Runner.run(
            quest_agent,
            message,
            history=history,
            run_config=RunConfig(workflow_name="quest_workflow")
        )


        updated_history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": result.final_output}
        ]

        quest_state = session.get("quest_state", {})
        save_session(quest_id, quest_state, updated_history)

        return {
            "message": result.final_output
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
