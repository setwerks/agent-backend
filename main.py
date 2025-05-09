from fastapi import FastAPI, Request, HTTPException
from agents import Agent, Runner, function_tool
import os
import requests
import uvicorn
from typing import Optional
import logging
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ✅ Define FastAPI app *before* launching Uvicorn
app = FastAPI()

# Set OpenAI API Key (optional if already set in the environment)
api_key = os.getenv("OPENAI_API_KEY", "")
if not api_key:
    logger.warning("OPENAI_API_KEY not set in environment variables")
os.environ["OPENAI_API_KEY"] = api_key

# Add request/response logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    try:
        body = await request.body()
        logger.info(f"Request body: {body.decode('utf-8')}")
    except Exception as e:
        logger.warning(f"Could not read request body: {e}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

# ✅ Define and register the tool using the decorator
@function_tool
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

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        return "Error: The geocoding service took too long to respond."
    except requests.RequestException as e:
        return f"Error fetching location data: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"

    if not data:
        return f"Sorry, I couldn't find '{location}'."

    result = data[0]
    lat = result["lat"]
    lon = result["lon"]
    map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"
    return f"{location} is at latitude {lat}, longitude {lon}. [View on Map]({map_url})"

# ✅ Create agent with tool
onboarding_agent = Agent(
    name="onboarding-chat-assistant",
    instructions="You are a helpful assistant that guides users through onboarding. Use tools if needed.",
    tools=[geocode_location],
    model="gpt-4"  # Fixed model name
)

# ✅ Define API endpoint
@app.post("/onboard-agent-chat")
async def agent_chat(request: Request):
    try:
        logger.info("Received new chat request")
        body = await request.json()
        logger.info(f"Request JSON: {body}")
        message = body.get("message")

        if not message:
            logger.warning("Request missing 'message' field")
            raise HTTPException(status_code=400, detail="Missing 'message' in request body")

        logger.info(f"Processing message: {message[:100]}...")
        result = await Runner.run(
            onboarding_agent,
            message,
            run_config={"workflow_name": "onboarding_flow"}
        )
        logger.info(f"Successfully processed message. Trace ID: {result.trace_id}")

        return {
            "message": result.final_output,
            "trace_id": result.trace_id
        }

    except HTTPException as he:
        logger.error(f"HTTP Exception: {str(he)}")
        raise he
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        timeout_keep_alive=30,
        access_log=True
    )