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
from typing import Optional, List, Dict, Any
from agents import Agent, Runner, function_tool, RunConfig, RunContextWrapper, enable_verbose_stdout_logging
from dataclasses import dataclass
import tiktoken

# Load environment vars
load_dotenv()

# === SUPABASE CONFIG ===
SUPABASE_API = os.getenv("SUPABASE_API")  # e.g., https://xyz.supabase.co/rest/v1/quest_sessions
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# === TAXONOMY LOADED FROM EXTERNAL FILE ===
# Place your full taxonomy JSON in 'taxonomy.json' alongside this script,
# or set TAXONOMY_PATH env var to its path.
try:
    taxonomy_path = os.getenv("TAXONOMY_PATH", "taxonomy.json")
    with open(taxonomy_path, "r") as tf:
        TAXONOMY = json.load(tf)
except Exception as e:
    logging.error("Failed to load taxonomy from %s: %s", taxonomy_path, e)
    TAXONOMY = {}

# === SESSION MANAGEMENT TOOLS USING SUPABASE ===
@function_tool
async def load_session(session_id: str) -> Dict[str, Any]:
    url = f"{SUPABASE_API}?quest_id=eq.{session_id}"
    res = requests.get(url, headers=SUPABASE_HEADERS)
    if res.status_code != 200:
        logging.error("Supabase load_session error: %s %s", res.status_code, res.text)
        return {"quest_state": {}, "chat_history": []}
    data = res.json()
    if not data:
        logging.info("Creating new session for session_id: %s", session_id)
        init_payload = {"quest_id": session_id, "quest_state": {}, "chat_history": [], "last_updated": datetime.utcnow().isoformat()}
        create = requests.post(SUPABASE_API, headers=SUPABASE_HEADERS, json=init_payload)
        create.raise_for_status()
        return {"quest_state": {}, "chat_history": []}
    record = data[0]
    return {"quest_state": record.get("quest_state", {}), "chat_history": record.get("chat_history", [])}

@function_tool
async def save_session(session_id: str, quest_state: Dict[str, Any], chat_history: List[Any]) -> Dict[str, str]:
    state_copy = quest_state.copy()
    state_copy.pop('ui', None)
    payload = {"quest_id": session_id, "quest_state": state_copy, "chat_history": chat_history, "last_updated": datetime.utcnow().isoformat()}
    url = f"{SUPABASE_API}?quest_id=eq.{session_id}"
    res = requests.patch(url, headers=SUPABASE_HEADERS, json=payload)
    res.raise_for_status()
    return {"session_id": session_id}

@function_tool
def update_quest_state(ctx: RunContextWrapper, field: str, value: Any) -> str:
    ctx.context.quest_state[field] = value
    logging.info("[update_quest_state] Set %s = %s", field, value)
    return f"Saved `{field}`."

# === CLASSIFICATION TOOL USING LLM ONLY ===
class Classification(BaseModel):
    general_category: str
    sub_category: str  # or Optional[str]

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
        # Parse the assistant’s JSON output
        content = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content)
        # Construct a Classification, which Auto-validates and
        # informs the schema generator of the exact fields.
        return Classification(**parsed)
    except Exception as e:
        logging.error(f"Classification parse error: {e}, response: {data}")
        # Fallback to a safe default
        return Classification(
            general_category="general",
            sub_category=""
        )
# === PROMPT TEMPLATES ===
FOR_SALE_PROMPT = """
You are a 'for sale' quest agent. Gather the item's title, price or price range, condition, and optionally photos. Then ask for the location or confirm it.
After collecting each piece of info, call update_quest_state. Save session at end.
Output the updated quest_state as JSON prefixed by '###JSON###'.
"""
HOUSING_PROMPT = """
You are a 'housing' quest agent. Determine if the user is looking to rent, buy, or sublet. Gather details: property type, budget range, move-in date, and location specifics (neighborhood, distance). After each step, call update_quest_state. Save session at end. Output JSON '###JSON###' with updated quest_state.
"""
JOBS_PROMPT = """
You are a 'jobs' quest agent. Identify job role, full-time or part-time, desired industry, experience level required, and preferred work location (remote/on-site). Ask for resume upload if needed. After each step, call update_quest_state. Save session at end. Output updated quest_state in JSON prefixed with '###JSON###'.
"""
SERVICES_PROMPT = """
You are a 'services' quest agent. Find out what type of service is needed (e.g., plumbing, tutoring), desired timeframe, budget, and any relevant qualifications or certifications the provider must have. After each step, call update_quest_state. Save session at end. Output '###JSON###' JSON updated quest_state.
"""
COMMUNITY_PROMPT = """
You are a 'community' quest agent. Gather details: activity description, date/time, meetup location, group size, and any costs (if applicable). After each step, call update_quest_state. Save session at end. Output updated quest_state JSON prefixed by '###JSON###'.
"""
GIGS_PROMPT = """
You are a 'gigs' quest agent. Determine gig type (e.g., labor, creative), duration or dates required, pay rate or budget, location or remote flexibility, and any portfolio or sample work. After each step, call update_quest_state. Save session at end. Output JSON '###JSON###' with updated quest_state.
"""

# === DEFINE CATEGORY-SPECIFIC AGENTS ===
category_agents = { ... }  # existing definitions
dynamic_agent = Agent(
    name="quest_generic",
    instructions="You are a generic quest agent. Ask clarifying questions.",
    tools=[function_tool(load_session), function_tool(classify_quest), function_tool(update_quest_state), create_quest, function_tool(save_session)],
    model="gpt-4o"
)

# === FASTAPI SETUP ===
app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@dataclass
class QuestContext:
    quest_state: Dict[str, Any]
    chat_history: List[Any]

@app.post("/start-quest")
async def start_quest(request: Request):
    body = await request.json()
    session_id = body.get("session_id") or str(uuid4())
    message = body.get("message", "")

    # Load previous session
    loaded = await load_session(session_id)
    context = RunContextWrapper(context=QuestContext(
        quest_state=loaded["quest_state"],
        chat_history=loaded["chat_history"]
    ))

    # Append user message to history
    context.context.chat_history.append({"role": "user", "content": message})

    # Only classify if not already classified
    if "general_category" not in context.context.quest_state:
        classifier_agent = Agent(
            name="quest_classifier",
            instructions="Classify the user request into Craigslist general and sub categories.",
            tools=[function_tool(classify_quest)],
            model="gpt-4o",
        )
        class_result = await Runner.run(
            starting_agent=classifier_agent,
            input=[{"role": "user", "content": message}],
            context=context,
            run_config=RunConfig(workflow_name="classification_workflow")
        )
        context.context.quest_state.update(class_result)
        context.context.chat_history.append({"role": "assistant", "content": json.dumps(class_result)})

    # Select and run agent based on classification
    gen_cat = context.context.quest_state.get("general_category")
    onboarding_agent = category_agents.get(gen_cat, dynamic_agent)
    result = await Runner.run(
        starting_agent=onboarding_agent,
        input=[{"role": "user", "content": message}],
        context=context,
        run_config=RunConfig(workflow_name="quest_workflow")
    )

    # Parse and update state
    parsed = json.loads(result.final_output)
    context.context.quest_state.update(parsed)
    context.context.chat_history.append({"role": "assistant", "content": result.final_output})

    # Save session
    await save_session(session_id, context.context.quest_state, context.context.chat_history)

    return {"status": "ok", "session_id": session_id, "quest_state": context.context.quest_state}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
