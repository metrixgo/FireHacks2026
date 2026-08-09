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
    weights: Dict[str, float] = {"distance": 0.4, "aqi": 0.3, "greenery": 0.15, "safety": 0.15}

class RouteResponse(BaseModel):
    summary: str
    routes: List[Dict[str, Any]]
    target_distance: float
    actual_distances: List[float]
    weights_used: Dict[str, float]

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
    safety_score: float = 90.0,
    weights: Dict[str, float] = None,
    variations: Dict[str, float] = None
) -> Dict[str, float]:
    """Calculate overall route score using weighted formula."""
    if weights is None:
        weights = {"distance": 0.4, "aqi": 0.3, "greenery": 0.15, "safety": 0.15}
    
    if variations is None:
        variations = {"aqi_modifier": 1.0, "greenery_modifier": 1.0, "safety_modifier": 1.0}
    
    s_dist = calculate_distance_score(actual_distance, target_distance)
    s_aqi = calculate_aqi_score(aqi) * variations["aqi_modifier"]
    s_green = greenery_score * variations["greenery_modifier"]
    s_safe = safety_score * variations["safety_modifier"]
    
    # Clamp scores to 0-100
    s_aqi = max(0, min(100, s_aqi))
    s_green = max(0, min(100, s_green))
    s_safe = max(0, min(100, s_safe))
    
    # Weighted formula
    score = (weights["distance"] * s_dist) + (weights["aqi"] * s_aqi) + (weights["greenery"] * s_green) + (weights["safety"] * s_safe)
    
    return {
        "total_score": score,
        "distance_score": s_dist,
        "aqi_score": s_aqi,
        "greenery_score": s_green,
        "safety_score": s_safe,
        "weights": weights
    }

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
        # Fallback: Generate simple circular routes if no API key
        print("ORS API key not configured, using fallback route generation")
        return generate_fallback_routes(latitude, longitude, target_distance)
    
    routes = []
    
    try:
        # Generate 3 different round-trip routes with different bearings
        bearings = [0, 120, 240]  # North, Southeast, Southwest
        
        for bearing in bearings:
            # Calculate approximate target point for round trip
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
                },
                timeout=30
            )
            
            if response.status_code == 200:
                geojson = response.json()
                if geojson.get("features"):
                    route_feature = geojson["features"][0]
                    
                    # Calculate actual distance from route
                    distance_meters = route_feature["properties"]["segments"][0]["distance"]
                    distance_miles = distance_meters * 0.000621371
                    
                    # Extract turn-by-turn directions if available
                    steps = []
                    if "steps" in route_feature["properties"]["segments"][0]:
                        steps = route_feature["properties"]["segments"][0]["steps"]
                    else:
                        # Generate basic steps from coordinates
                        coords = route_feature["geometry"]["coordinates"]
                        for i in range(len(coords) - 1):
                            bearing = calculate_bearing(coords[i][1], coords[i][0], coords[i+1][1], coords[i+1][0])
                            dist = calculate_distance_between_points(coords[i][1], coords[i][0], coords[i+1][1], coords[i+1][0])
                            steps.append({
                                "instruction": get_direction_instruction(bearing, i, len(coords), "custom"),
                                "distance": dist,
                                "bearing": bearing,
                                "coordinates": coords[i+1]
                            })
                    
                    route_feature["properties"]["segments"][0]["steps"] = steps
                    route_feature["properties"]["pattern"] = "ors_route"
                    route_feature["properties"]["description"] = "Route via OpenRouteService"
                    
                    routes.append({
                        "geojson": route_feature,
                        "distance": distance_miles,
                        "distance_meters": distance_meters,
                        "pattern": "ors_route"
                    })
            else:
                print(f"ORS API error: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"Error generating routes with ORS: {e}")
        # Fallback to simple routes
        return generate_fallback_routes(latitude, longitude, target_distance)
    
    # If no routes generated, use fallback
    if not routes:
        print("No routes generated from ORS, using fallback")
        return generate_fallback_routes(latitude, longitude, target_distance)
    
    return routes

def generate_fallback_routes(latitude: float, longitude: float, target_distance: float) -> List[Dict]:
    """Generate realistic round-trip routes when ORS is unavailable."""
    import math
    import random
    
    routes = []
    
    # Generate different route patterns
    route_patterns = [
        "out_and_back",    # Go out and return same path
        "loop",            # Circular loop
        "figure_eight",    # Figure-8 pattern
        "lollipop",        # Out to a loop, return same path
        "triangle"         # Triangular route
    ]
    
    for pattern_idx, pattern in enumerate(route_patterns):
        waypoints = [[longitude, latitude]]  # Start at user location
        
        # Calculate route based on pattern
        if pattern == "out_and_back":
            # Go in one direction, then return
            bearing = random.uniform(0, 360)
            distance = target_distance / 2
            
            # Calculate intermediate point
            bearing_rad = math.radians(bearing)
            half_dist_deg = (distance / 2) / 111000
            
            mid_lat = latitude + half_dist_deg * math.cos(bearing_rad)
            mid_lon = longitude + half_dist_deg * math.sin(bearing_rad) / math.cos(math.radians(latitude))
            
            # End point (turnaround)
            end_lat = latitude + (distance / 111000) * math.cos(bearing_rad)
            end_lon = longitude + (distance / 111000) * math.sin(bearing_rad) / math.cos(math.radians(latitude))
            
            waypoints.append([mid_lon, mid_lat])
            waypoints.append([end_lon, end_lat])
            waypoints.append([mid_lon, mid_lat])
            waypoints.append([longitude, latitude])
            
        elif pattern == "loop":
            # Create a realistic loop with varying radius
            num_points = 12
            base_radius = (target_distance / (2 * math.pi)) / 111000
            
            for i in range(num_points + 1):
                angle = (2 * math.pi * i) / num_points
                # Add some variation to make it more realistic
                variation = random.uniform(0.8, 1.2)
                radius = base_radius * variation
                
                point_lat = latitude + radius * math.cos(angle)
                point_lon = longitude + radius * math.sin(angle) / math.cos(math.radians(latitude))
                waypoints.append([point_lon, point_lat])
                
        elif pattern == "figure_eight":
            # Figure-8 pattern
            num_points = 16
            radius = (target_distance / 4) / 111000  # Smaller loops for figure-8
            
            for i in range(num_points + 1):
                t = (2 * math.pi * i) / num_points
                # Figure-8 parametric equations
                x = radius * math.sin(t)
                y = radius * math.sin(t) * math.cos(t)
                
                point_lat = latitude + y / math.cos(math.radians(latitude))
                point_lon = longitude + x
                waypoints.append([point_lon, point_lat])
                
        elif pattern == "lollipop":
            # Out to a loop, return same way
            stick_length = target_distance * 0.3
            loop_length = target_distance * 0.7
            loop_radius = (loop_length / (2 * math.pi)) / 111000
            stick_dist_deg = (stick_length / 111000)
            
            bearing = random.uniform(0, 360)
            bearing_rad = math.radians(bearing)
            
            # End of the stick
            loop_center_lat = latitude + stick_dist_deg * math.cos(bearing_rad)
            loop_center_lon = longitude + stick_dist_deg * math.sin(bearing_rad) / math.cos(math.radians(latitude))
            
            waypoints.append([loop_center_lon, loop_center_lat])
            
            # Create the loop
            num_loop_points = 8
            for i in range(num_loop_points + 1):
                angle = (2 * math.pi * i) / num_loop_points
                point_lat = loop_center_lat + loop_radius * math.cos(angle)
                point_lon = loop_center_lon + loop_radius * math.sin(angle) / math.cos(math.radians(loop_center_lat))
                waypoints.append([point_lon, point_lat])
            
            # Return via stick
            waypoints.append([loop_center_lon, loop_center_lat])
            waypoints.append([longitude, latitude])
            
        elif pattern == "triangle":
            # Triangular route
            side_length = target_distance / 3
            side_deg = side_length / 111000
            
            # First vertex
            bearing1 = random.uniform(0, 360)
            bearing1_rad = math.radians(bearing1)
            
            v1_lat = latitude + side_deg * math.cos(bearing1_rad)
            v1_lon = longitude + side_deg * math.sin(bearing1_rad) / math.cos(math.radians(latitude))
            
            # Second vertex (120 degrees from first)
            bearing2 = bearing1 + 120
            bearing2_rad = math.radians(bearing2)
            
            v2_lat = v1_lat + side_deg * math.cos(bearing2_rad)
            v2_lon = v1_lon + side_deg * math.sin(bearing2_rad) / math.cos(math.radians(v1_lat))
            
            waypoints.append([v1_lon, v1_lat])
            waypoints.append([v2_lon, v2_lat])
            waypoints.append([longitude, latitude])
        
        # Calculate actual distance (approximate)
        total_distance = 0
        for i in range(len(waypoints) - 1):
            lat1, lon1 = waypoints[i][1], waypoints[i][0]
            lat2, lon2 = waypoints[i+1][1], waypoints[i+1][0]
            
            # Haversine formula
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
            c = 2 * math.asin(math.sqrt(a))
            total_distance += 6371000 * c  # Earth's radius in meters
        
        # Add some realistic variation to make routes more unique
        # Add small random perturbations to waypoints
        for i in range(1, len(waypoints) - 1):  # Don't modify start/end points
            perturbation = random.uniform(-0.0001, 0.0001)  # Small perturbation in degrees
            waypoints[i][1] += perturbation  # Latitude
            waypoints[i][0] += perturbation / math.cos(math.radians(waypoints[i][1]))  # Longitude
        
        # Adjust to match target distance better
        scale_factor = target_distance / total_distance if total_distance > 0 else 1
        
        # Create GeoJSON with turn-by-turn information
        # Add pattern-specific variation to make routes more realistic
        pattern_variations = {
            "out_and_back": {"aqi_modifier": 0.9, "greenery_modifier": 0.8, "safety_modifier": 0.9},
            "loop": {"aqi_modifier": 1.1, "greenery_modifier": 1.2, "safety_modifier": 1.0},
            "figure_eight": {"aqi_modifier": 1.0, "greenery_modifier": 1.1, "safety_modifier": 0.9},
            "lollipop": {"aqi_modifier": 1.2, "greenery_modifier": 1.3, "safety_modifier": 1.1},
            "triangle": {"aqi_modifier": 0.95, "greenery_modifier": 0.9, "safety_modifier": 1.0}
        }
        
        variations = pattern_variations.get(pattern, {"aqi_modifier": 1.0, "greenery_modifier": 1.0, "safety_modifier": 1.0})
        
        geojson = {
            "type": "Feature",
            "properties": {
                "segments": [{
                    "distance": total_distance,
                    "duration": total_distance / 1.4,  # Approximate walking speed
                    "steps": generate_turn_by_turn(waypoints, pattern)
                }],
                "pattern": pattern,
                "description": f"{pattern.replace('_', ' ').title()} route",
                "variations": variations
            },
            "geometry": {
                "type": "LineString",
                "coordinates": waypoints
            }
        }
        
        distance_miles = total_distance * 0.000621371
        
        routes.append({
            "geojson": geojson,
            "distance": distance_miles,
            "distance_meters": total_distance,
            "pattern": pattern
        })
    
    return routes

def generate_turn_by_turn(waypoints: List, pattern: str) -> List[Dict]:
    """Generate turn-by-turn directions for the route."""
    steps = []
    
    for i in range(len(waypoints) - 1):
        current = waypoints[i]
        next_point = waypoints[i + 1]
        
        # Calculate bearing
        bearing = calculate_bearing(current[1], current[0], next_point[1], next_point[0])
        
        step = {
            "instruction": get_direction_instruction(bearing, i, len(waypoints), pattern),
            "distance": calculate_distance_between_points(current[1], current[0], next_point[1], next_point[0]),
            "bearing": bearing,
            "coordinates": next_point
        }
        steps.append(step)
    
    return steps

def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate bearing between two points."""
    import math
    dlon = math.radians(lon2 - lon1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    
    bearing = math.atan2(y, x)
    bearing = math.degrees(bearing)
    bearing = (bearing + 360) % 360
    
    return bearing

def calculate_distance_between_points(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in meters."""
    import math
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return 6371000 * c

def get_direction_instruction(bearing: float, step_index: int, total_steps: int, pattern: str) -> str:
    """Generate human-readable direction instruction."""
    if step_index == 0:
        return f"Start your {pattern.replace('_', ' ')} route"
    
    if step_index == total_steps - 1:
        return "Return to starting point"
    
    # Convert bearing to direction
    if bearing >= 337.5 or bearing < 22.5:
        direction = "North"
    elif bearing >= 22.5 and bearing < 67.5:
        direction = "Northeast"
    elif bearing >= 67.5 and bearing < 112.5:
        direction = "East"
    elif bearing >= 112.5 and bearing < 157.5:
        direction = "Southeast"
    elif bearing >= 157.5 and bearing < 202.5:
        direction = "South"
    elif bearing >= 202.5 and bearing < 247.5:
        direction = "Southwest"
    elif bearing >= 247.5 and bearing < 292.5:
        direction = "West"
    else:
        direction = "Northwest"
    
    return f"Head {direction}"

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
    
    try:
        # Step 1: Extract target distance using AI
        target_distance = extract_target_distance(request.prompt)
        print(f"Target distance: {target_distance} meters")
        
        # Step 2: Get AQI data
        aqi = get_aqi_data(request.latitude, request.longitude)
        print(f"AQI: {aqi}")
        
        # Step 3: Generate candidate routes
        routes = generate_routes(request.latitude, request.longitude, target_distance)
        print(f"Generated {len(routes)} routes")
        
        if not routes:
            raise HTTPException(status_code=500, detail="Failed to generate routes")
        
        # Step 4: Score and rank routes with detailed breakdown
        scored_routes = []
        actual_distances = []
        
        for route in routes:
            actual_distances.append(route["distance_meters"])
            
            # Get variations from route properties if available
            variations = route["geojson"]["properties"].get("variations", 
                {"aqi_modifier": 1.0, "greenery_modifier": 1.0, "safety_modifier": 1.0})
            
            score_details = calculate_route_score(
                route["distance_meters"],
                target_distance,
                aqi,
                weights=request.weights,
                variations=variations
            )
            
            scored_routes.append({
                "geojson": route["geojson"],
                "distance": route["distance"],
                "distance_meters": route["distance_meters"],
                "aqi": round(aqi, 1),
                "score": score_details["total_score"],
                "score_breakdown": {
                    "distance_score": score_details["distance_score"],
                    "aqi_score": score_details["aqi_score"],
                    "greenery_score": score_details["greenery_score"],
                    "safety_score": score_details["safety_score"]
                },
                "pattern": route.get("pattern", "unknown"),
                "description": route["geojson"]["properties"].get("description", "Custom route"),
                "turn_by_turn": route["geojson"]["properties"]["segments"][0].get("steps", [])
            })
        
        # Sort by score (descending)
        scored_routes.sort(key=lambda x: x["score"], reverse=True)
        
        # Step 5: Generate AI summary for best route
        best_route = scored_routes[0]
        summary = generate_ai_summary(request.prompt, best_route)
        
        return RouteResponse(
            summary=summary,
            routes=scored_routes,
            target_distance=target_distance,
            actual_distances=actual_distances,
            weights_used=request.weights
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in plan_route: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Health check endpoint
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "API is working"}

# Serve static files (must be after API routes)
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
