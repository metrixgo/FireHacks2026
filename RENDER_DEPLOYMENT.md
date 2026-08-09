# Render Deployment Configuration

## Exact Render Settings

### Build Command
```
pip install -r requirements.txt
```

### Start Command
```
uvicorn app:app --host 0.0.0.0 --port $PORT
```

### Environment Variables
| Variable | Value | Description |
|----------|-------|-------------|
| `PORT` | `8080` | Port for the web server |
| `FEATHERLESS_API_KEY` | `your_api_key_here` | Your Featherless API key for AI functionality |
| `DATA_ROOT` | `/opt/render/project/rooms` | Path for persistent disk storage |

### Persistent Disk Configuration
- **Name**: `data`
- **Mount Path**: `/opt/render/project/rooms`
- **Size**: `1 GB`

## Deployment Steps

1. **Create Web Service**
   - Go to Render Dashboard
   - Click "New +" → "Web Service"
   - Connect your GitHub repository

2. **Configure Basic Settings**
   - **Name**: `ai-code-editor-agent` (or your preferred name)
   - **Region**: Choose nearest region
   - **Branch**: `main` (or your default branch)

3. **Configure Runtime**
   - **Runtime**: `Python`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`

4. **Add Environment Variables**
   - Navigate to "Environment" section
   - Add the following variables:
     ```
     PORT = 8080
     FEATHERLESS_API_KEY = <your_actual_api_key>
     DATA_ROOT = /opt/render/project/rooms
     ```

5. **Add Persistent Disk**
   - Navigate to "Advanced" section
   - Click "Add Disk"
   - Configure:
     - **Name**: `data`
     - **Mount Path**: `/opt/render/project/rooms`
     - **Size**: `1 GB`

6. **Deploy**
   - Click "Create Web Service"
   - Wait for deployment to complete
   - Access your app at the provided URL

## Troubleshooting

### Application fails to start
- Check that all environment variables are set correctly
- Verify the Featherless API key is valid
- Check Render logs for specific error messages

### Room data not persisting
- Ensure the persistent disk is properly mounted
- Verify `DATA_ROOT` environment variable matches disk mount path
- Check disk is not full (upgrade size if needed)

### AI commands not working
- Verify `FEATHERLESS_API_KEY` is set and valid
- Check Featherless API status
- Review Render logs for API communication errors

## Cost Estimates

- **Web Service**: Free tier available (512 MB RAM, 0.1 CPU)
- **Persistent Disk**: ~$0.25/GB/month (1 GB = ~$0.25/month)
- **Total**: Approximately $0.25/month for basic deployment