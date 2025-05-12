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
from quest_prompts import FOR_SALE_PROMPT, HOUSING_PROMPT, JOBS_PROMPT, SERVICES_PROMPT, COMMUNITY_PROMPT, GIGS_PROMPT
from quest_agents import category_agents, dynamic_agent

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

# === SESSION MANAGEMENT TOOLS USING SUPABASE ===
from quest_tools import (
    load_session,
    save_session,
    update_quest_state,
    classify_quest,
    confirm_location,
    geocode_location,
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
            tools=[classify_quest],
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
    logging.info(f"Agent output: {result.final_output}")  # Log the raw output

    # Parse and update state
    parsed = json.loads(result.final_output)
    context.context.quest_state.update(parsed)
    context.context.chat_history.append({"role": "assistant", "content": result.final_output})

    # Save session
    await save_session(session_id, context.context.quest_state, context.context.chat_history)

    return {"status": "ok", "session_id": session_id, "quest_state": context.context.quest_state}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
