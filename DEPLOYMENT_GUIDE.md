# AI Exercise Route Planner - Render Deployment Guide

This guide provides step-by-step instructions for deploying the AI-Powered Exercise Route Planner to Render.

## 📋 Prerequisites

Before deploying, ensure you have:

1. **Render Account** - Create a free account at [render.com](https://render.com)
2. **GitHub Repository** - Push your code to a GitHub repository
3. **API Keys**:
   - [Featherless AI API Key](https://featherless.ai/) - For AI route summaries
   - [OpenRouteService API Key](https://openrouteservice.org/) - For route generation
4. **Python 3.8+** - For local testing
5. **Node.js 16+** - For frontend building

## 🔑 Required API Keys

### Featherless AI API
1. Sign up at [featherless.ai](https://featherless.ai/)
2. Get your API key from the dashboard
3. Used for: Extracting user intent and generating route summaries

### OpenRouteService API
1. Sign up at [openrouteservice.org](https://openrouteservice.org/)
2. Get your free API key (limited to 2000 requests/day)
3. Used for: Generating walking/running routes

## 🚀 Deployment Steps

### Part 1: Deploy Backend (FastAPI)

#### 1. Create Backend Service
1. Go to Render Dashboard
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Configure the following:

**Basic Settings:**
- **Name**: `ai-route-planner-backend`
- **Region**: Choose nearest region (e.g., Oregon, Frankfurt)
- **Branch**: `main`

**Build & Runtime:**
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Advanced:**
- **Root Directory**: `backend`

#### 2. Add Environment Variables
Navigate to **"Environment"** section and add:

| Variable | Value | Description |
|----------|-------|-------------|
| `PORT` | `8000` | Server port |
| `FEATHERLESS_API_KEY` | `your_actual_api_key` | Featherless AI API key |
| `ORS_API_KEY` | `your_actual_api_key` | OpenRouteService API key |

#### 3. Deploy
1. Click **"Create Web Service"**
2. Wait for deployment to complete (2-3 minutes)
3. Copy the backend URL (e.g., `https://ai-route-planner-backend.onrender.com`)

#### 4. Test Backend
```bash
curl https://ai-route-planner-backend.onrender.com/health
```
Expected response: `{"status":"ok","message":"AI Exercise Route Planner is running"}`

---

### Part 2: Deploy Frontend (React)

#### 1. Create Frontend Service
1. Go to Render Dashboard
2. Click **"New +"** → **"Static Site"**
3. Connect your GitHub repository
4. Configure the following:

**Basic Settings:**
- **Name**: `ai-route-planner-frontend`
- **Region**: Same region as backend
- **Branch**: `main`

**Build Settings:**
- **Root Directory**: `frontend`
- **Build Command**: `npm install && npm run build`
- **Publish Directory**: `dist`

#### 2. Add Environment Variables
Navigate to **"Environment"** section and add:

| Variable | Value | Description |
|----------|-------|-------------|
| `VITE_API_URL` | `https://ai-route-planner-backend.onrender.com` | Your backend URL from Part 1 |

#### 3. Deploy
1. Click **"Create Static Site"**
2. Wait for deployment to complete (1-2 minutes)
3. Access your frontend at the provided URL

---

## 🧪 Testing the Deployed Application

### 1. Test Backend Health
```bash
curl https://ai-route-planner-backend.onrender.com/health
```

### 2. Test Route Planning API
```bash
curl -X POST https://ai-route-planner-backend.onrender.com/api/plan-route \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 40.7128,
    "longitude": -74.0060,
    "prompt": "I want to run for 5 miles"
  }'
```

### 3. Test Frontend
1. Open your frontend URL in a browser
2. Click "Use My Location" or enter coordinates
3. Enter a prompt like "I want to run for 5 miles"
4. Click "Find Best Route"
5. Verify the map displays and route cards appear

---

## 🔧 Troubleshooting

### Backend Issues

**Problem**: Backend fails to start
- **Solution**: Check Render logs for specific error messages
- **Common causes**: Missing API keys, dependency installation failures

**Problem**: API timeouts
- **Solution**: Render free tier may spin down services; first request might be slow
- **Optimization**: Consider upgrading to paid tier for consistent performance

**Problem**: CORS errors
- **Solution**: Backend CORS is configured to allow all origins; verify no firewall issues

### Frontend Issues

**Problem**: Frontend can't connect to backend
- **Solution**: Verify `VITE_API_URL` environment variable is set correctly
- **Check**: Backend URL is accessible and health check passes

**Problem**: Map doesn't load
- **Solution**: Check browser console for errors; verify internet connection
- **Note**: OpenStreetMap tiles require internet access

**Problem**: Build fails
- **Solution**: Check build logs in Render dashboard
- **Common causes**: Node version incompatibility, dependency issues

### API Integration Issues

**Problem**: OpenRouteService API errors
- **Solution**: Verify API key is valid and within rate limits
- **Check**: [ORS Dashboard](https://openrouteservice.org/dev/#/login) for usage stats

**Problem**: Featherless AI not responding
- **Solution**: Verify API key and check Featherless service status
- **Fallback**: App uses simple parsing if AI fails

**Problem**: OpenAQ API no data
- **Solution**: API may not have data for all locations; app uses default AQI of 50

---

## 📊 Cost Estimates

### Free Tier Usage
- **Backend Web Service**: Free (512 MB RAM, 0.1 CPU)
- **Frontend Static Site**: Free
- **Total**: $0/month

### Paid Tier (if needed)
- **Backend Standard**: ~$7/month (1 GB RAM, 1 CPU)
- **Frontend**: Still free on static site
- **API Costs**: 
  - OpenRouteService: Free tier (2000 requests/day)
  - Featherless AI: Check current pricing

---

## 🔒 Security Considerations

1. **API Keys**: Never commit real API keys to GitHub
2. **Environment Variables**: Always use Render's environment variable system
3. **CORS**: Current setup allows all origins; restrict in production if needed
4. **Rate Limiting**: Consider implementing rate limiting for production use

---

## 🚀 Performance Optimization

1. **Backend**: 
   - Implement caching for AQI data
   - Add request rate limiting
   - Use connection pooling for API calls

2. **Frontend**:
   - Implement lazy loading for map tiles
   - Add service worker for offline support
   - Optimize bundle size

---

## 📝 Maintenance

1. **Monitor**: Check Render logs regularly
2. **Update**: Keep dependencies updated
3. **API Keys**: Rotate API keys periodically
4. **Scaling**: Upgrade resources if needed based on usage

---

## 🎯 Next Steps

After successful deployment:

1. **Customize**: Update UI colors, branding, and features
2. **Enhance**: Add more sophisticated scoring algorithms
3. **Integrate**: Add user authentication and saved routes
4. **Monitor**: Set up analytics and error tracking
5. **Scale**: Upgrade to paid tier if usage increases

---

## 📞 Support

If you encounter issues:

1. **Render Documentation**: [docs.render.com](https://docs.render.com)
2. **FastAPI Docs**: [fastapi.tiangolo.com](https://fastapi.tiangolo.com)
3. **React Docs**: [react.dev](https://react.dev)
4. **ORS Support**: [openrouteservice.org](https://openrouteservice.org)
5. **Featherless Support**: [featherless.ai](https://featherless.ai)

---

## ✅ Deployment Checklist

- [ ] Backend deployed and health check passing
- [ ] Frontend deployed and accessible
- [ ] Environment variables configured for both services
- [ ] API keys added to backend environment
- [ ] Frontend can successfully call backend API
- [ ] Map displays correctly in browser
- [ ] Route planning works end-to-end
- [ ] AI summaries are generated
- [ ] Air quality data is fetched
- [ ] Candidate routes are scored and ranked

Congratulations! Your AI Exercise Route Planner is now live on Render! 🎉
