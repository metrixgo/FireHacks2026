from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
import math
import os
from typing import List, Dict, Any
import json

app = FastAPI(title="AI Exercise Route Planner")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/", StaticFiles(directory=".", html=True), name="static")

# API Keys
FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY")
ORS_API_KEY = os.getenv("ORS_API_KEY")

# API Endpoints
FEATHERLESS_API_URL = "https://api.featherless.ai/v1"
ORS_API_URL = "https://api.openrouteservice.org"
OPENAQ_API_URL = "https://api.openaq.org/v2"

class RouteRequest(BaseModel):
    latitude: float
    longitude: float
    prompt: str

class RouteResponse(BaseModel):
    summary: str
    routes: List[Dict[str, Any]]

def calculate_distance_score(actual_distance: float, target_distance: float) -> float:
    """Calculate distance score using exponential decay."""
    if target_distance == 0:
        return 0.0
    variance = abs(actual_distance - target_distance) / target_distance
    return 100.0 * math.exp(-variance)

def calculate_aqi_score(aqi: float) -> float:
    """Calculate air quality score (normalized 0-300)."""
    return max(0.0, 100.0 * (1 - (aqi / 200.0)))

def calculate_route_score(
    actual_distance: float,
    target_distance: float,
    aqi: float,
    greenery_score: float = 85.0,
    safety_score: float = 90.0
) -> float:
    """Calculate overall route score using weighted formula."""
    s_dist = calculate_distance_score(actual_distance, target_distance)
    s_aqi = calculate_aqi_score(aqi)
    s_green = greenery_score
    s_safe = safety_score
    
    # Weighted formula
    score = (0.4 * s_dist) + (0.3 * s_aqi) + (0.15 * s_green) + (0.15 * s_safe)
    return score

def extract_target_distance(prompt: str) -> float:
    """Use Featherless AI to extract target distance from prompt."""
    if not FEATHERLESS_API_KEY:
        # Fallback: simple parsing
        prompt_lower = prompt.lower()
        if "mile" in prompt_lower:
            # Extract number before "mile"
            import re
            match = re.search(r'(\d+\.?\d*)\s*mile', prompt_lower)
            if match:
                return float(match.group(1)) * 1609.34  # Convert to meters
        elif "km" in prompt_lower or "kilometer" in prompt_lower:
            import re
            match = re.search(r'(\d+\.?\d*)\s*(km|kilometer)', prompt_lower)
            if match:
                return float(match.group(1)) * 1000  # Convert to meters
        return 5000.0  # Default 5km
    
    try:
        response = requests.post(
            f"{FEATHERLESS_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {FEATHERLESS_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [
                    {
                        "role": "system",
                        "content": "Extract the target distance in meters from the user's exercise prompt. Return only the number, no other text."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            distance_text = result["choices"][0]["message"]["content"].strip()
            # Extract number from response
            import re
            match = re.search(r'(\d+\.?\d*)', distance_text)
            if match:
                return float(match.group(1))
        
        return 5000.0  # Default fallback
    except Exception as e:
        print(f"Error extracting distance with AI: {e}")
        return 5000.0

def get_aqi_data(latitude: float, longitude: float) -> float:
    """Fetch AQI data from OpenAQ API."""
    try:
        # Find nearest measurement station
        response = requests.get(
            f"{OPENAQ_API_URL}/measurements",
            params={
                "coordinates": f"{latitude},{longitude}",
                "radius": 50000,  # 50km radius
                "parameter": "pm25",
                "limit": 1,
                "sort": "desc",
                "order_by": "datetime"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("results") and len(data["results"]) > 0:
                pm25 = data["results"][0].get("value")
                if pm25 is not None:
                    # Convert PM2.5 to approximate AQI
                    # Simplified conversion
                    if pm25 <= 12:
                        return pm25 * (50 / 12)
                    elif pm25 <= 35.4:
                        return 50 + (pm25 - 12) * (50 / 23.4)
                    elif pm25 <= 55.4:
                        return 100 + (pm25 - 35.4) * (50 / 20)
                    else:
                        return 150 + (pm25 - 55.4) * (50 / 35.4)
        
        return 50.0  # Default moderate AQI
    except Exception as e:
        print(f"Error fetching AQI: {e}")
        return 50.0

def generate_routes(latitude: float, longitude: float, target_distance: float) -> List[Dict]:
    """Generate candidate routes using OpenRouteService."""
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS API key not configured")
    
    routes = []
    
    try:
        # Generate 3 different round-trip routes with different bearings
        bearings = [0, 120, 240]  # North, Southeast, Southwest
        
        for bearing in bearings:
            # Calculate approximate target point for round trip
            # This is a simplified approach - for production, use proper routing
            import math
            
            # Convert bearing to radians
            bearing_rad = math.radians(bearing)
            
            # Approximate distance to target (half of total for round trip)
            half_distance = (target_distance / 2) / 111000  # Rough conversion to degrees
            
            target_lat = latitude + half_distance * math.cos(bearing_rad)
            target_lon = longitude + half_distance * math.sin(bearing_rad) / math.cos(math.radians(latitude))
            
            # Get route from ORS
            response = requests.post(
                f"{ORS_API_URL}/v2/directions/foot-walking/geojson",
                headers={
                    "Authorization": ORS_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "coordinates": [
                        [longitude, latitude],
                        [target_lon, target_lat],
                        [longitude, latitude]
                    ]
                }
            )
            
            if response.status_code == 200:
                geojson = response.json()
                if geojson.get("features"):
                    route_feature = geojson["features"][0]
                    
                    # Calculate actual distance from route
                    distance_meters = route_feature["properties"]["segments"][0]["distance"]
                    distance_miles = distance_meters * 0.000621371
                    
                    routes.append({
                        "geojson": route_feature,
                        "distance": distance_miles,
                        "distance_meters": distance_meters
                    })
            
    except Exception as e:
        print(f"Error generating routes: {e}")
    
    return routes

def generate_ai_summary(prompt: str, best_route: Dict) -> str:
    """Generate AI summary for the best route."""
    if not FEATHERLESS_API_KEY:
        return f"Based on your request to {prompt.lower()}, I found a {best_route['distance']:.2f} mile route with a score of {best_route['score']:.1f}/100. This route offers good air quality and safe walking conditions."
    
    try:
        response = requests.post(
            f"{FEATHERLESS_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {FEATHERLESS_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful exercise route assistant. Provide a brief, friendly summary of the recommended route based on the user's goals and route characteristics."
                    },
                    {
                        "role": "user",
                        "content": f"User wants: {prompt}\n\nRecommended route: {best_route['distance']:.2f} miles, Score: {best_route['score']:.1f}/100, AQI: {best_route['aqi']}"
                    }
                ],
                "max_tokens": 150,
                "temperature": 0.7
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        
        return f"Recommended route: {best_route['distance']:.2f} miles with a score of {best_route['score']:.1f}/100."
    except Exception as e:
        print(f"Error generating AI summary: {e}")
        return f"Recommended route: {best_route['distance']:.2f} miles with a score of {best_route['score']:.1f}/100."

@app.post("/api/plan-route")
async def plan_route(request: RouteRequest) -> RouteResponse:
    """Main endpoint to plan exercise routes."""
    
    # Step 1: Extract target distance using AI
    target_distance = extract_target_distance(request.prompt)
    
    # Step 2: Get AQI data
    aqi = get_aqi_data(request.latitude, request.longitude)
    
    # Step 3: Generate candidate routes
    routes = generate_routes(request.latitude, request.longitude, target_distance)
    
    if not routes:
        raise HTTPException(status_code=500, detail="Failed to generate routes")
    
    # Step 4: Score and rank routes
    scored_routes = []
    for route in routes:
        score = calculate_route_score(
            route["distance_meters"],
            target_distance,
            aqi
        )
        scored_routes.append({
            "geojson": route["geojson"],
            "distance": route["distance"],
            "aqi": round(aqi, 1),
            "score": score
        })
    
    # Sort by score (descending)
    scored_routes.sort(key=lambda x: x["score"], reverse=True)
    
    # Step 5: Generate AI summary for best route
    best_route = scored_routes[0]
    summary = generate_ai_summary(request.prompt, best_route)
    
    return RouteResponse(
        summary=summary,
        routes=scored_routes
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
