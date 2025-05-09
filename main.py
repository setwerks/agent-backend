from fastapi import FastAPI, Request
from agents import Agent, Runner, Tool
import os
import requests

app = FastAPI()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

# ✅ Define the function
def geocode_location(location: str) -> str:
    """Get coordinates and a map preview for a location."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": location,
        "format": "json",
        "limit": 1
    }
    headers = {
        "User-Agent": "Questor-Agent/1.0"
    }

    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    data = response.json()

    if not data:
        return f"Sorry, I couldn't find '{location}'."

    result = data[0]
    lat = result["lat"]
    lon = result["lon"]
    map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
    return f"{location} is at latitude {lat}, longitude {lon}. [View on Map]({map_url})"

# ✅ Register it as a Tool
geo_tool = Tool(
    name="geocode_location",
    description="Get coordinates and a map preview for a location.",
    function=geocode_location
)

# ✅ Create agent with the tool
onboarding_agent = Agent(
    name="onboarding-chat-assistant",
    instructions="You are a helpful assistant that guides users through onboarding. Use tools if needed.",
    tools=[geo_tool]
)

# ✅ FastAPI route
@app.post("/onboard-agent-chat")
async def agent_chat(request: Request):
    body = await request.json()
    message = body.get("message")

    if not message:
        return {"error": "Missing 'message'"}

    result = await Runner.run(onboarding_agent, message)

    return {
        "message": result.final_output,
        "trace_id": result.trace_id
    }

