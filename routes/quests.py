from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field
import os
import requests
from typing import List, Optional, Any, Dict

router = APIRouter()

SUPABASE_API = os.getenv("SUPABASE_API")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class QuestState(BaseModel):
    # Core fields
    want_or_have: Optional[str] = None
    description: Optional[str] = None
    general_location: Optional[str] = None
    location_confirmed: Optional[bool] = None
    distance: Optional[float] = None
    distance_unit: Optional[str] = None
    price: Optional[float] = None
    photos: Optional[List[str]] = Field(default_factory=list)
    action: Optional[str] = None
    text: Optional[str] = None
    ui: Optional[dict] = None
    # For Sale specific
    condition: Optional[str] = None
    title: Optional[str] = None
    # Housing specific
    property_type: Optional[str] = None
    budget: Optional[float] = None
    move_in_date: Optional[str] = None
    # Jobs specific
    job_role: Optional[str] = None
    employment_type: Optional[str] = None
    industry: Optional[str] = None
    experience_level: Optional[str] = None
    work_location: Optional[str] = None
    resume_uploaded: Optional[bool] = None
    # Services specific
    service_type: Optional[str] = None
    timeframe: Optional[str] = None
    qualifications: Optional[str] = None
    # Community specific
    activity: Optional[str] = None
    date_time: Optional[str] = None
    meetup_location: Optional[str] = None
    group_size: Optional[int] = None
    cost: Optional[float] = None
    # Gigs specific
    gig_type: Optional[str] = None
    duration: Optional[str] = None
    pay_rate: Optional[float] = None
    portfolio: Optional[List[str]] = None

class QuestCreateRequest(QuestState):
    user_id: str

@router.post("/api/quests/save")
async def create_quest(request: QuestCreateRequest):
    # Validate required fields (Pydantic does this, but you can add more)
    if not request.want_or_have or not request.description or not request.user_id:
        raise HTTPException(status_code=400, detail="Missing required fields")

    # Prepare data for Supabase
    data = request.dict()
    try:
        response = requests.post(
            f"{SUPABASE_API}/rest/v1/quests",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            json=[data]  # Supabase expects a list of records
        )
        if response.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Supabase error: {response.text}")
        return {"success": True, "quest": response.json()[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save quest: {str(e)}")

class QuestUpdateRequest(BaseModel):
    updates: Dict[str, Any]

@router.put("/api/quests/{quest_id}")
async def update_quest(quest_id: str = Path(...), request: QuestUpdateRequest = None):
    if not request or not request.updates:
        raise HTTPException(status_code=400, detail="No update fields provided")
    try:
        response = requests.patch(
            f"{SUPABASE_API}/rest/v1/quests?id=eq.{quest_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            json=request.updates
        )
        if response.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Supabase error: {response.text}")
        updated = response.json()
        if not updated:
            raise HTTPException(status_code=404, detail="Quest not found or not updated")
        return {"success": True, "quest": updated[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update quest: {str(e)}") 