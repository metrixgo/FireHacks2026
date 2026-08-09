# AI-Powered Exercise Route Planner

A lightweight, AI-powered exercise route planner with a split-screen UI that helps users find optimal walking and running routes based on their preferences.

## Features

- **AI-Powered Planning**: Uses natural language processing to understand exercise goals
- **Smart Route Scoring**: Ranks routes based on distance accuracy, air quality, greenery, and safety
- **Interactive Map**: Visual interface with route display and selection
- **Real-time AQI**: Fetches local air quality data for health-conscious routing
- **Minimal Setup**: No build tools required - just vanilla HTML/CSS/JS and Python

## Tech Stack

### Frontend
- **Single HTML file** with embedded CSS and JavaScript
- **Leaflet.js** (via CDN) for interactive maps
- **OpenStreetMap** tiles for map rendering
- **Vanilla JavaScript** with Fetch API

### Backend
- **FastAPI** for REST API
- **Uvicorn** as ASGI server
- **Requests** for HTTP client calls
- **OpenAI-compatible API** (Featherless AI) for AI processing

### External APIs
- **Featherless AI**: OpenAI-compatible endpoint for NLP tasks
- **OpenRouteService**: Free routing API for route generation
- **OpenAQ**: Free air quality data API

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables
```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 3. Run the Server
```bash
python main.py
```

### 4. Open in Browser
Navigate to `http://localhost:8000`

## Project Structure

```
FireHacks2026/
├── index.html          # Frontend (HTML + CSS + JS)
├── main.py             # Backend (FastAPI)
├── requirements.txt    # Python dependencies
├── .env.example       # Environment variables template
├── DEPLOYMENT.md      # Deployment guide
└── README.md          # This file
```

## Route Scoring Algorithm

Routes are scored using a weighted formula:

```
Score(r) = (0.4 × S_dist) + (0.3 × S_aqi) + (0.15 × S_green) + (0.15 × S_safe)
```

- **Distance Score**: Exponential decay based on target distance variance
- **Air Quality Score**: Normalized AQI (0-300 scale)
- **Greenery Score**: Park/greenery proximity (baseline: 85.0)
- **Safety Score**: Pedestrian path safety (baseline: 90.0)

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions on Render.com.

## API Keys Required

1. **Featherless AI** - Get at [featherless.ai](https://featherless.ai)
2. **OpenRouteService** - Get free key at [openrouteservice.org](https://openrouteservice.org)

## Usage Example

1. Click "📍 Auto" to detect your location
2. Enter your goal: "I want to run for 5 miles"
3. Click "Find Best Route"
4. View AI recommendations and click routes to see them on the map

## License

MIT License - Feel free to use this project for learning and development.
