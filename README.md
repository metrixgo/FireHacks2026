# FireHacks2026
Project for Fire Hacks 2026

## AI Code Editor Agent

A collaborative, AI-assisted web terminal that allows users to create and execute commands in sandboxed environments using natural language prompts.

## Features

- **AI Terminal Agent**: Accept user prompts to perform file operations and execute commands
- **Web Terminal & File System**: Live interactive browser execution
- **Real-time Collaboration**: Multiple users can work in the same room simultaneously
- **Sandboxed Environments**: Each room operates in an isolated directory
- **Featherless AI Integration**: Uses Qwen/Qwen2.5-7B-Instruct model for command generation

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variable (optional for testing without AI):
```bash
set FEATHERLESS_API_KEY=your_api_key_here
```

3. Run the application:
```bash
python app.py
```

4. Open browser to `http://localhost:8080`

## Render Deployment

### Build Command
```
pip install -r requirements.txt
```

### Start Command
```
uvicorn app:app --host 0.0.0.0 --port $PORT
```

### Environment Variables
- `PORT`: 8080
- `FEATHERLESS_API_KEY`: Your Featherless API key (required for AI functionality)
- `DATA_ROOT`: /opt/render/project/rooms (for persistent disk storage)

### Persistent Disk
- Mount Path: `/opt/render/project/rooms`
- Size: 1 GB
- Name: data

### Manual Render Setup

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure settings:
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variables:
   - `PORT` = `8080`
   - `FEATHERLESS_API_KEY` = (your Featherless API key)
   - `DATA_ROOT` = `/opt/render/project/rooms`
5. Add a Persistent Disk:
   - Mount Path: `/opt/render/project/rooms`
   - Size: 1 GB
6. Deploy

## Usage

1. Create a new room or join an existing one using a 6-character code
2. Type natural language prompts (e.g., "Create a Python script that adds two numbers")
3. Review the AI-generated command
4. Approve and execute the command
5. View results in the terminal log
6. Share the room code with others for real-time collaboration
