# 🏃 AI-Powered Exercise Route Planner

An intelligent web application that helps users find optimal running and walking routes based on air quality, safety, scenery, and distance preferences using AI-powered analysis.

## ✨ Features

- **AI-Powered Route Planning**: Uses Featherless AI to understand natural language requests
- **Real-time Air Quality**: Integrates OpenAQ API for current air quality data
- **Smart Route Scoring**: Mathematical model to rank routes based on multiple factors
- **Interactive Maps**: Split-screen UI with React-Leaflet and OpenStreetMap
- **Route Comparison**: View multiple candidate routes with detailed breakdowns
- **Responsive Design**: Mobile-first approach with adaptive layout

## 🏗️ Architecture

### Tech Stack

**Frontend:**
- React with Vite
- React-Leaflet for interactive maps
- OpenStreetMap tiles
- Axios for API calls
- Lucide-React icons

**Backend:**
- Python FastAPI
- Uvicorn server
- OpenAI SDK (configured for Featherless AI)
- Pydantic for data validation
- Requests for HTTP calls

**External APIs:**
- Featherless AI (`Qwen/Qwen2.5-7B-Instruct`) - Intent extraction and summaries
- OpenRouteService - Route generation
- OpenAQ - Air quality data

## 📊 Route Scoring Algorithm

Each route is scored on a scale of 0-100 using:

```
Score(r) = (0.4 × S_dist) + (0.3 × S_aqi) + (0.15 × S_green) + (0.15 × S_safe)
```

**Components:**
- **Distance Score**: Penalizes deviation from target distance
- **Air Quality Score**: Based on AQI (0-300 scale)
- **Greenery Score**: Route attributes and park proximity
- **Safety Score**: Footway and pedestrian path density

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+
- API Keys (Featherless AI, OpenRouteService)

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd ai-exercise-route-planner
```

2. **Install dependencies**
```bash
npm run install:all
```

3. **Configure environment variables**

Backend (`backend/.env`):
```
FEATHERLESS_API_KEY=your_featherless_api_key
ORS_API_KEY=your_openrouteservice_api_key
```

Frontend (`frontend/.env`):
```
VITE_API_URL=http://localhost:8000
```

4. **Run development servers**
```bash
npm run dev
```

This starts both backend (port 8000) and frontend (port 5173) simultaneously.

## 📁 Project Structure

```
ai-exercise-route-planner/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── requirements.txt     # Python dependencies
│   └── .env.example         # Environment variables template
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # Main React component
│   │   ├── App.css         # Component styles
│   │   └── main.jsx        # React entry point
│   ├── package.json         # Node dependencies
│   └── .env.example        # Environment variables template
├── package.json             # Root package scripts
└── DEPLOYMENT_GUIDE.md     # Deployment instructions
```

## 🔌 API Endpoints

### Backend Endpoints

**Health Check**
```
GET /health
```

**Plan Route**
```
POST /api/plan-route
Content-Type: application/json

{
  "latitude": 40.7128,
  "longitude": -74.0060,
  "prompt": "I want to run for 5 miles"
}
```

**Response**
```json
{
  "ai_summary": "This 5.02-mile route is perfect for your run...",
  "target_meters": 8046.72,
  "target_miles": 5.0,
  "activity": "running",
  "local_aqi": 45,
  "candidate_routes": [...],
  "selected_route": {...}
}
```

## 🧪 Testing

### Test Backend Health
```bash
curl http://localhost:8000/health
```

### Test Route Planning
```bash
curl -X POST http://localhost:8000/api/plan-route \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 40.7128,
    "longitude": -74.0060,
    "prompt": "I want to run for 5 miles"
  }'
```

## 🌐 Deployment

### Deploy to Render

Follow the detailed deployment guide in [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

**Quick Summary:**
1. Deploy backend as Python Web Service
2. Deploy frontend as Static Site
3. Configure environment variables
4. Update frontend API URL to point to backend

## 🔑 API Keys Setup

### Featherless AI
1. Sign up at [featherless.ai](https://featherless.ai/)
2. Get API key from dashboard
3. Add to backend environment variables

### OpenRouteService
1. Sign up at [openrouteservice.org](https://openrouteservice.org/)
2. Get free API key (2000 requests/day)
3. Add to backend environment variables

## 📱 Usage

1. **Grant Location Access**: Click "Use My Location" or enter coordinates manually
2. **Enter Prompt**: Type natural language request (e.g., "I want to run for 5 miles")
3. **Find Routes**: Click "Find Best Route" to generate candidate routes
4. **View Results**: 
   - AI summary explains the recommended route
   - Compare candidate routes with detailed scores
   - Click routes to view them on the map
5. **Navigate**: Use the interactive map to explore the selected route

## 🎨 UI Features

### Left Panel (AI & Route Control)
- Coordinate input with geolocation
- Natural language prompt input
- AI-generated route summaries
- Candidate route list with scores
- Detailed breakdown metrics

### Right Panel (Map View)
- Full-height interactive Leaflet map
- OpenStreetMap tiles
- Route polyline visualization
- User location marker
- Automatic recentering

## 🔧 Development

### Available Scripts

```bash
npm run install:frontend    # Install frontend dependencies
npm run install:backend     # Install backend dependencies
npm run install:all         # Install all dependencies
npm run dev:backend         # Start backend server only
npm run dev:frontend        # Start frontend dev server only
npm run dev                 # Start both servers
npm run build:frontend      # Build frontend for production
```

## 🐛 Troubleshooting

### Backend Issues
- **API Key Errors**: Verify environment variables are set correctly
- **Dependencies**: Run `pip install -r requirements.txt` in backend directory
- **Port Conflicts**: Ensure port 8000 is available

### Frontend Issues
- **Map Not Loading**: Check internet connection (OSM tiles require internet)
- **API Connection**: Verify `VITE_API_URL` is set correctly
- **Build Errors**: Clear node_modules and reinstall dependencies

### API Integration Issues
- **ORS Rate Limits**: Free tier limited to 2000 requests/day
- **AI Timeouts**: Featherless AI may have response delays
- **AQI Data**: Not all locations have air quality monitoring

## 📄 License

This project is open source and available for educational purposes.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📞 Support

For deployment issues, refer to [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

---

Built with ❤️ using AI-powered route planning technology
