# Deployment Guide - AI Exercise Route Planner

This guide will help you deploy the AI Exercise Route Planner to Render.com.

## Prerequisites

1. **Render Account**: Sign up at [render.com](https://render.com)
2. **GitHub Account**: Push your code to a GitHub repository
3. **API Keys**: Obtain the required API keys (see Environment Variables section)

## Step 1: Prepare Your Repository

Ensure your repository has the following structure:
```
FireHacks2026/
├── index.html
├── main.py
├── requirements.txt
└── DEPLOYMENT.md
```

## Step 2: Set Up Environment Variables

You'll need the following API keys:

### Featherless AI API Key
1. Sign up at [featherless.ai](https://featherless.ai)
2. Get your API key from the dashboard
3. This is an OpenAI-compatible endpoint

### OpenRouteService API Key
1. Sign up at [openrouteservice.org](https://openrouteservice.org)
2. Get your free API key from the dashboard
3. This provides routing services

## Step 3: Deploy Backend to Render

### 3.1 Create a New Web Service

1. Go to Render Dashboard → "New +" → "Web Service"
2. Connect your GitHub repository
3. Configure the service:

**Build & Runtime Settings:**
- **Name**: `ai-route-planner-api`
- **Region**: Choose nearest region
- **Branch**: `main`
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python main.py`

**Environment Variables:**
Add the following environment variables:
- `FEATHERLESS_API_KEY`: Your Featherless AI API key
- `ORS_API_KEY`: Your OpenRouteService API key

### 3.2 Deploy

Click "Create Web Service" and wait for deployment. Render will:
- Clone your repository
- Install dependencies from requirements.txt
- Start the FastAPI server
- Provide a URL like `https://ai-route-planner-api.onrender.com`

## Step 4: Update Frontend for Production

The frontend currently points to `http://localhost:8000`. Update it to use your production backend URL.

In `index.html`, find this line:
```javascript
const response = await fetch('http://localhost:8000/api/plan-route', {
```

Replace with your Render backend URL:
```javascript
const response = await fetch('https://ai-route-planner-api.onrender.com/api/plan-route', {
```

## Step 5: Deploy Frontend to Render

### 5.1 Create a Static Site

1. Go to Render Dashboard → "New +" → "Static Site"
2. Connect your GitHub repository
3. Configure:

**Settings:**
- **Name**: `ai-route-planner-frontend`
- **Branch**: `main`
- **Root Directory**: `.` (repository root)
- **Build Command**: Leave empty (no build needed)
- **Publish Directory**: `.` (serves from root)

### 5.2 Deploy

Click "Create Static Site". Render will:
- Serve your `index.html` as a static site
- Provide a URL like `https://ai-route-planner-frontend.onrender.com`

## Step 6: Test Your Deployment

1. Visit your frontend URL
2. Click "📍 Auto" to detect your location
3. Enter a prompt like "I want to run for 5 miles"
4. Click "Find Best Route"
5. Verify the map displays routes and AI recommendations appear

## Alternative: Single Service Deployment

For simplicity, you can deploy everything as a single web service since `main.py` serves the static files:

1. Follow Step 3 (Web Service deployment)
2. The FastAPI app serves `index.html` at the root URL
3. Access everything at one URL: `https://ai-route-planner-api.onrender.com`

## Local Development

To run locally:

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export FEATHERLESS_API_KEY="your_key_here"
export ORS_API_KEY="your_key_here"
```

3. Run the server:
```bash
python main.py
```

4. Open `http://localhost:8000` in your browser

## Troubleshooting

### Backend fails to start
- Check Render logs for error messages
- Verify all environment variables are set
- Ensure `requirements.txt` has correct versions

### Frontend can't connect to backend
- Verify the backend URL in `index.html` is correct
- Check CORS settings (currently set to allow all origins)
- Ensure backend is deployed and running

### API rate limits
- OpenRouteService free tier has limits
- Featherless AI may have usage limits
- Consider upgrading plans for production use

### Map not displaying
- Check browser console for errors
- Verify Leaflet CDN is accessible
- Ensure coordinates are valid

## Production Considerations

1. **Error Handling**: Add more robust error handling for API failures
2. **Rate Limiting**: Implement rate limiting for your API endpoints
3. **Authentication**: Add user authentication if needed
4. **Caching**: Cache route results to reduce API calls
5. **Monitoring**: Set up logging and monitoring
6. **HTTPS**: Render automatically provides HTTPS certificates

## Cost Estimate

- **Render Free Tier**: 
  - Web Service: Free (with spin-up delay)
  - Static Site: Free
- **APIs**:
  - Featherless AI: Pay-per-use
  - OpenRouteService: Free tier available
  - OpenAQ: Free

The application can run entirely on free tiers for development and testing.
