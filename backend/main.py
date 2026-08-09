import os
import math
import json
import requests
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="AI Exercise Route Planner")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Keys
FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY")
ORS_API_KEY = os.getenv("ORS_API_KEY")

# Initialize OpenAI client for Featherless
if FEATHERLESS_API_KEY:
    client = OpenAI(
        base_url="https://api.featherless.ai/v1",
        api_key=FEATHERLESS_API_KEY
    )

# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

class RouteRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="User's latitude")
    longitude: float = Field(..., ge=-180, le=180, description="User's longitude")
    prompt: str = Field(..., min_length=1, description="User's natural language prompt")

class RouteCandidate(BaseModel):
    id: str
    distance_meters: float
    distance_miles: float
    geojson: Dict[str, Any]
    aqi: int
    score_dist: float
    score_aqi: float
    score_green: float
    score_safe: float
    overall_score: float

class RouteResponse(BaseModel):
    ai_summary: str
    target_meters: float
    target_miles: float
    activity: str
    local_aqi: int
    candidate_routes: List[RouteCandidate]
    selected_route: RouteCandidate

# -----------------------------------------------------------------------------
# Route Scoring Functions
# -----------------------------------------------------------------------------

def calculate_distance_score(actual_distance: float, target_distance: float) -> float:
    """Calculate distance score (0-100) based on deviation from target."""
    if target_distance == 0:
        return 0.0
    deviation = abs(actual_distance - target_distance) / target_distance
    return 100.0 * math.exp(-deviation)

def calculate_aqi_score(aqi: int) -> float:
    """Calculate air quality score (0-100) based on AQI."""
    return max(0.0, 100.0 * (1 - (aqi / 200.0)))

def calculate_greenery_score(route_data: Dict[str, Any]) -> float:
    """Calculate greenery score based on route attributes."""
    # Placeholder: In production, analyze route for park proximity, green spaces
    # For now, return a baseline score
    return 85.0

def calculate_safety_score(route_data: Dict[str, Any]) -> float:
    """Calculate safety score based on footway/pedestrian path density."""
    # Placeholder: In production, analyze route for pedestrian infrastructure
    # For now, return a baseline score
    return 90.0

def calculate_overall_score(
    distance_score: float,
    aqi_score: float,
    greenery_score: float,
    safety_score: float
) -> float:
    """Calculate overall route score using the specified formula."""
    return (
        0.4 * distance_score +
        0.3 * aqi_score +
        0.15 * greenery_score +
        0.15 * safety_score
    )

# -----------------------------------------------------------------------------
# API Integration Functions
# -----------------------------------------------------------------------------

def extract_intent_with_ai(prompt: str) -> Dict[str, Any]:
    """Use Featherless AI to extract target distance and activity type from prompt."""
    if not FEATHERLESS_API_KEY:
        # Fallback to simple parsing if no API key
        return {"target_meters": 5000, "activity": "running"}
    
    try:
        response = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[
                {
                    "role": "system",
                    "content": "Extract the target distance (in meters) and activity type from the user's prompt. Return ONLY a JSON object with keys 'target_meters' (number) and 'activity' (string: 'running' or 'walking')."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.strip("`").replace("json", "").strip()
        
        return json.loads(content)
    except Exception as e:
        print(f"AI intent extraction error: {e}")
        # Fallback values
        return {"target_meters": 5000, "activity": "running"}

def get_local_aqi(latitude: float, longitude: float) -> int:
    """Fetch local air quality using OpenAQ API."""
    try:
        url = f"https://api.openaq.org/v2/latest?coordinates={latitude},{longitude}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("results") and len(data["results"]) > 0:
                # Get PM2.5 value and convert to AQI
                measurements = data["results"][0].get("measurements", [])
                for meas in measurements:
                    if meas.get("parameter") == "pm25":
                        pm25 = meas.get("value", 50)
                        # Simple PM2.5 to AQI conversion
                        if pm25 <= 12:
                            return int(pm25 * 50 / 12)
                        elif pm25 <= 35.4:
                            return int(50 + (pm25 - 12) * 50 / 23.4)
                        elif pm25 <= 55.4:
                            return int(100 + (pm25 - 35.4) * 50 / 20)
                        else:
                            return int(150 + (pm25 - 55.4) * 50 / 35.4)
        
        # Default AQI if no data available
        return 50
    except Exception as e:
        print(f"OpenAQ API error: {e}")
        return 50  # Default moderate AQI

def generate_candidate_routes(
    latitude: float, 
    longitude: float, 
    target_meters: float,
    activity: str
) -> List[Dict[str, Any]]:
    """Generate candidate routes using OpenRouteService API."""
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY not configured")
    
    candidates = []
    
    # Generate 3 different routes with different bearing seeds
    bearings = [0, 120, 240]  # North, Southeast, Southwest
    
    for i, bearing in enumerate(bearings):
        try:
            # Calculate a point in the target direction
            target_lat = latitude + (target_meters / 111320) * math.cos(math.radians(bearing))
            target_lon = longitude + (target_meters / (111320 * math.cos(math.radians(latitude)))) * math.sin(math.radians(bearing))
            
            url = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"
            headers = {"Authorization": ORS_API_KEY}
            params = {
                "start": f"{longitude},{latitude}",
                "end": f"{target_lon},{target_lat}"
            }
            
            response = requests.post(url, headers=headers, json=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("features") and len(data["features"]) > 0:
                    route_feature = data["features"][0]
                    distance_meters = route_feature["properties"]["segments"][0]["distance"]
                    
                    # Create round-trip by going back
                    round_trip_distance = distance_meters * 2
                    
                    candidates.append({
                        "id": f"route_{i}",
                        "distance_meters": round_trip_distance,
                        "geojson": route_feature,
                        "bearing": bearing
                    })
        except Exception as e:
            print(f"ORS API error for bearing {bearing}: {e}")
            continue
    
    return candidates

def generate_ai_summary(
    selected_route: RouteCandidate,
    target_miles: float,
    activity: str,
    local_aqi: int
) -> str:
    """Generate AI summary for the selected route."""
    if not FEATHERLESS_API_KEY:
        return f"Best {activity} route: {selected_route.distance_miles:.2f} miles with AQI {local_aqi}."
    
    try:
        response = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful exercise route assistant. Provide a concise, friendly 2-3 sentence summary explaining why this route is the best option based on distance, air quality, and overall score."
                },
                {
                    "role": "user",
                    "content": f"Selected route: {selected_route.distance_miles:.2f} miles, AQI: {local_aqi}, Overall score: {selected_route.overall_score:.1f}/100. Target was {target_miles:.2f} miles for {activity}."
                }
            ],
            temperature=0.7,
            max_tokens=150
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI summary generation error: {e}")
        return f"Best {activity} route: {selected_route.distance_miles:.2f} miles with AQI {local_aqi}."

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "AI Exercise Route Planner is running"}

@app.post("/api/plan-route", response_model=RouteResponse)
def plan_route(request: RouteRequest):
    """Main endpoint to plan exercise routes based on user prompt and location."""
    
    # Step 1: Extract intent using AI
    intent = extract_intent_with_ai(request.prompt)
    target_meters = intent.get("target_meters", 5000)
    activity = intent.get("activity", "running")
    target_miles = target_meters * 0.000621371
    
    # Step 2: Get local air quality
    local_aqi = get_local_aqi(request.latitude, request.longitude)
    
    # Step 3: Generate candidate routes using ORS
    try:
        raw_candidates = generate_candidate_routes(
            request.latitude,
            request.longitude,
            target_meters,
            activity
        )
        
        if not raw_candidates:
            raise HTTPException(status_code=500, detail="Failed to generate candidate routes")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Route generation error: {str(e)}")
    
    # Step 4: Score each candidate route
    scored_candidates = []
    for candidate in raw_candidates:
        distance_score = calculate_distance_score(candidate["distance_meters"], target_meters)
        aqi_score = calculate_aqi_score(local_aqi)
        greenery_score = calculate_greenery_score(candidate["geojson"])
        safety_score = calculate_safety_score(candidate["geojson"])
        overall_score = calculate_overall_score(distance_score, aqi_score, greenery_score, safety_score)
        
        scored_candidates.append(RouteCandidate(
            id=candidate["id"],
            distance_meters=candidate["distance_meters"],
            distance_miles=candidate["distance_meters"] * 0.000621371,
            geojson=candidate["geojson"],
            aqi=local_aqi,
            score_dist=distance_score,
            score_aqi=aqi_score,
            score_green=greenery_score,
            score_safe=safety_score,
            overall_score=overall_score
        ))
    
    # Step 5: Sort by overall score (descending)
    scored_candidates.sort(key=lambda x: x.overall_score, reverse=True)
    
    # Step 6: Select top route
    selected_route = scored_candidates[0]
    
    # Step 7: Generate AI summary
    ai_summary = generate_ai_summary(selected_route, target_miles, activity, local_aqi)
    
    return RouteResponse(
        ai_summary=ai_summary,
        target_meters=target_meters,
        target_miles=target_miles,
        activity=activity,
        local_aqi=local_aqi,
        candidate_routes=scored_candidates,
        selected_route=selected_route
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
