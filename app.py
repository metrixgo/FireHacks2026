import json
import os
import re
import secrets
import string
import subprocess
from typing import Optional
from pathlib import Path

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI
import uvicorn

# -----------------------------------------------------------------------------
# 1. Environment & Sandbox Setup
# -----------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# All rooms live under this folder. Point DATA_ROOT at a Render Persistent
# Disk mount path if you want rooms to survive redeploys/restarts.
ROOMS_ROOT = Path(os.environ.get("DATA_ROOT", os.path.join(BASE_DIR, "rooms")))
ROOMS_ROOT.mkdir(parents=True, exist_ok=True)
ROOMS_ROOT = ROOMS_ROOT.resolve()

ROOM_ID_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")
ROOM_ID_RE = re.compile(r"^[A-Z0-9]{6}$")

FEATHERLESS_MODEL = "Qwen/Qwen2.5-7B-Instruct"

DANGEROUS_TOKENS = [
    "sudo", "rm -rf /", "rm -rf /*", " / ", "..", "~", "curl", "wget",
    ">/dev", "mkfs", "dd if=", ":(){", "shutdown", "reboot", "chmod -r 777",
]

app = FastAPI(title="AI Code Editor Agent — Rooms")

# -----------------------------------------------------------------------------
# 2. Room helpers
# -----------------------------------------------------------------------------

def generate_room_id() -> str:
    return "".join(secrets.choice(ROOM_ID_ALPHABET) for _ in range(6))


def room_dir_for(room_id: str) -> Path:
    """Returns the sandbox folder for a room, after strictly validating the id."""
    if not ROOM_ID_RE.match(room_id):
        raise HTTPException(status_code=400, detail="Invalid room code.")
    path = (ROOMS_ROOT / room_id).resolve()
    if ROOMS_ROOT not in path.parents and path != ROOMS_ROOT:
        raise HTTPException(status_code=400, detail="Invalid room code.")
    return path


def room_exists(room_id: str) -> bool:
    try:
        return room_dir_for(room_id).is_dir()
    except HTTPException:
        return False


def get_file_tree(workshop_dir: Path) -> str:
    if not workshop_dir.exists():
        return "(empty directory)"
    tree_lines = []
    entries = sorted(workshop_dir.rglob("*"))
    if not entries:
        return "(empty directory)"
    for entry in entries:
        rel = entry.relative_to(workshop_dir)
        depth = len(rel.parts) - 1
        indent = "  " * depth
        icon = "\U0001F4C1" if entry.is_dir() else "\U0001F4C4"
        tree_lines.append(f"{indent}{icon} {rel.name}{'/' if entry.is_dir() else ''}")
    return "\n".join(tree_lines)


def is_command_safe(command: str) -> tuple[bool, str]:
    """Lightweight guard against obvious sandbox-escape / destructive commands."""
    lowered = command.lower()
    for token in DANGEROUS_TOKENS:
        if token in lowered:
            return False, f"Command blocked: contains disallowed pattern '{token}'."
    return True, ""


# -----------------------------------------------------------------------------
# 3. WebSocket connection manager (per room)
# -----------------------------------------------------------------------------

class RoomManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, room_id: str, ws: WebSocket):
        await ws.accept()
        self.connections.setdefault(room_id, []).append(ws)
        await self.broadcast(room_id, {"type": "presence", "count": len(self.connections[room_id])})

    def disconnect(self, room_id: str, ws: WebSocket):
        conns = self.connections.get(room_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns and room_id in self.connections:
            del self.connections[room_id]

    async def broadcast(self, room_id: str, message: dict):
        dead = []
        for ws in self.connections.get(room_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room_id, ws)


manager = RoomManager()

# -----------------------------------------------------------------------------
# 4. Request models
# -----------------------------------------------------------------------------

class PromptRequest(BaseModel):
    prompt: str


class ExecuteRequest(BaseModel):
    command: str
    explanation: Optional[str] = ""
    user: Optional[str] = "collaborator"


# -----------------------------------------------------------------------------
# 5. Room lifecycle API
# -----------------------------------------------------------------------------

@app.post("/api/create-room")
def create_room():
    for _ in range(10):
        room_id = generate_room_id()
        path = ROOMS_ROOT / room_id
        if not path.exists():
            path.mkdir(parents=True)
            return {"room_id": room_id}
    raise HTTPException(status_code=500, detail="Could not allocate a room, try again.")


@app.get("/api/room-exists/{room_id}")
def check_room(room_id: str):
    room_id = room_id.strip().upper()
    return {"exists": room_exists(room_id)}


@app.get("/api/{room_id}/files")
def get_files(room_id: str):
    workshop_dir = room_dir_for(room_id.upper())
    if not workshop_dir.is_dir():
        raise HTTPException(status_code=404, detail="Room not found.")
    return {"tree": get_file_tree(workshop_dir)}


@app.post("/api/{room_id}/ai-command")
def generate_command(room_id: str, req: PromptRequest):
    if not room_exists(room_id.upper()):
        raise HTTPException(status_code=404, detail="Room not found.")

    api_key = os.environ.get("FEATHERLESS_API_KEY")
    if not api_key:
        return {
            "command": "echo 'FEATHERLESS_API_KEY environment variable missing'",
            "explanation": "Set FEATHERLESS_API_KEY in Render's Environment tab, then redeploy.",
        }

    try:
        client = OpenAI(base_url="https://api.featherless.ai/v1", api_key=api_key)

        system_prompt = (
            "You are a command-line AI assistant operating strictly inside a sandboxed "
            "working directory. Translate the user's natural language request into a "
            "single precise POSIX shell command using only relative paths. "
            "Never use absolute paths, '..', 'sudo', or network commands. "
            "Respond ONLY with a raw JSON object with exactly two keys:\n"
            '1. "command": the exact shell command string to execute.\n'
            '2. "explanation": a concise 1-2 sentence explanation.\n\n'
            "Example: "
            '{"command": "touch main.py", "explanation": "Creates an empty file named main.py."}\n'
            "Do not include markdown formatting or extra commentary."
        )

        response = client.chat.completions.create(
            model=FEATHERLESS_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.prompt},
            ],
            temperature=0.1,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        data = json.loads(content)
        return {
            "command": str(data.get("command", "")).strip(),
            "explanation": str(data.get("explanation", "")).strip(),
        }
    except json.JSONDecodeError:
        return {
            "command": "ls -la",
            "explanation": "Failed to parse structured JSON from Featherless AI response.",
        }
    except Exception as err:  # noqa: BLE001
        return {
            "command": "echo 'AI API Error'",
            "explanation": f"Error communicating with Featherless AI: {str(err)}",
        }


@app.post("/api/{room_id}/execute")
async def execute_command(room_id: str, req: ExecuteRequest):
    room_id = room_id.upper()
    workshop_dir = room_dir_for(room_id)
    if not workshop_dir.is_dir():
        raise HTTPException(status_code=404, detail="Room not found.")

    cmd = req.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    safe, reason = is_command_safe(cmd)
    if not safe:
        result = {"command": cmd, "stdout": "", "stderr": reason, "returncode": 1}
    else:
        try:
            res = subprocess.run(
                cmd, shell=True, cwd=str(workshop_dir),
                capture_output=True, text=True, timeout=30,
            )
            result = {
                "command": cmd, "stdout": res.stdout,
                "stderr": res.stderr, "returncode": res.returncode,
            }
        except subprocess.TimeoutExpired:
            result = {
                "command": cmd, "stdout": "",
                "stderr": "Command execution timed out after 30 seconds.", "returncode": 124,
            }
        except Exception as err:  # noqa: BLE001
            result = {"command": cmd, "stdout": "", "stderr": f"Execution error: {str(err)}", "returncode": 1}

    await manager.broadcast(room_id, {
        "type": "execution",
        "user": req.user or "collaborator",
        "explanation": req.explanation or "",
        **result,
    })
    await manager.broadcast(room_id, {"type": "files", "tree": get_file_tree(workshop_dir)})

    return result


@app.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str):
    room_id = room_id.upper()
    if not room_exists(room_id):
        await websocket.close(code=4404)
        return
    await manager.connect(room_id, websocket)
    try:
        while True:
            # We don't expect inbound messages from clients other than pings,
            # but we read to detect disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)


# -----------------------------------------------------------------------------
# 6. Frontend — Landing page (create / join a room)
# -----------------------------------------------------------------------------

LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Code Editor Agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body, html {
    height: 100%; background-color: #1e1e1e; color: #d4d4d4;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    display: flex; align-items: center; justify-content: center;
  }
  .panel {
    width: 360px; border: 1px solid #333; background-color: #252526;
    padding: 24px; border-radius: 4px;
  }
  .title { font-size: 15px; font-weight: bold; color: #fff; margin-bottom: 4px; }
  .subtitle { font-size: 12px; color: #858585; margin-bottom: 20px; }
  button {
    width: 100%; padding: 10px; font-family: inherit; font-size: 13px;
    background-color: #238636; color: #fff; border: none; border-radius: 2px;
    cursor: pointer; margin-bottom: 10px;
  }
  button:hover { background-color: #2ea043; }
  .divider { text-align: center; color: #555; font-size: 11px; margin: 16px 0; }
  input {
    width: 100%; padding: 10px; font-family: inherit; font-size: 13px;
    background-color: #0d0d0d; color: #d4d4d4; border: 1px solid #333;
    border-radius: 2px; margin-bottom: 10px; text-transform: uppercase;
  }
  .join-btn { background-color: #2d2d2d; }
  .join-btn:hover { background-color: #3a3a3a; }
  .error { color: #f14c4c; font-size: 12px; margin-top: -4px; margin-bottom: 10px; min-height: 14px; }
</style>
</head>
<body>
  <div class="panel">
    <div class="title">⚡ AI CODE EDITOR AGENT</div>
    <div class="subtitle">Sandboxed, collaborative, AI-assisted terminal.</div>
    <button onclick="createRoom()">CREATE NEW ROOM</button>
    <div class="divider">— or join an existing room —</div>
    <input id="joinCode" placeholder="Room code (e.g. AB12CD)" maxlength="6" onkeydown="if(event.key==='Enter') joinRoom()">
    <div class="error" id="joinError"></div>
    <button class="join-btn" onclick="joinRoom()">JOIN ROOM</button>
  </div>
<script>
async function createRoom() {
  const res = await fetch('/api/create-room', { method: 'POST' });
  const data = await res.json();
  window.location.href = '/room/' + data.room_id;
}
async function joinRoom() {
  const codeInput = document.getElementById('joinCode');
  const code = codeInput.value.trim().toUpperCase();
  const errorEl = document.getElementById('joinError');
  errorEl.textContent = '';
  if (code.length !== 6) {
    errorEl.textContent = 'Room codes are 6 characters.';
    return;
  }
  const res = await fetch('/api/room-exists/' + code);
  const data = await res.json();
  if (!data.exists) {
    errorEl.textContent = 'Room not found.';
    return;
  }
  window.location.href = '/room/' + code;
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return LANDING_HTML


# -----------------------------------------------------------------------------
# 7. Frontend — Room page (editor + terminal, real-time synced)
# -----------------------------------------------------------------------------

ROOM_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Room __ROOM_ID__ — AI Code Editor Agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body, html {
    height: 100%; background-color: #1e1e1e; color: #d4d4d4;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    overflow: hidden;
  }
  .container { display: flex; flex-direction: column; height: 100vh; width: 100vw; }
  .header {
    height: 42px; background-color: #252526; border-bottom: 1px solid #333;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 16px; font-size: 13px;
  }
  .header-title { font-weight: bold; color: #fff; display: flex; align-items: center; gap: 8px; }
  .header-right { display: flex; align-items: center; gap: 10px; }
  .room-badge {
    background-color: #0d0d0d; border: 1px solid #333; padding: 3px 8px;
    border-radius: 3px; font-size: 11px; color: #4ec9b0; cursor: pointer;
  }
  .presence-badge {
    background-color: #1e1e1e; border: 1px solid #333; padding: 3px 8px;
    border-radius: 3px; font-size: 11px; color: #888;
  }
  .workspace { display: flex; flex: 1; overflow: hidden; }
  .sidebar { width: 280px; border-right: 1px solid #333; background-color: #202020; padding: 12px; overflow-y: auto; }
  .sidebar-section-title { font-size: 11px; color: #858585; letter-spacing: 1px; margin-bottom: 8px; }
  .sidebar-row { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; }
  .template-btn {
    display: block; width: 100%; text-align: left; background-color: #2d2d2d;
    color: #d4d4d4; border: none; padding: 8px 10px; font-family: inherit;
    font-size: 12px; border-radius: 2px; margin-bottom: 6px; cursor: pointer;
  }
  .template-btn:hover { background-color: #3a3a3a; }
  .refresh-btn { background: none; border: none; color: #888; cursor: pointer; font-size: 12px; }
  .file-tree-container {
    margin-top: 6px; font-size: 12px; color: #9cdcfe; white-space: pre-wrap;
    background-color: #0d0d0d; border: 1px solid #333; padding: 8px; border-radius: 2px; min-height: 80px;
  }
  .main-content { flex: 1; display: flex; flex-direction: column; padding: 12px; gap: 8px; overflow: hidden; }
  .terminal-log {
    flex: 1; background-color: #0d0d0d; border: 1px solid #333; border-radius: 2px;
    padding: 10px; font-size: 12px; overflow-y: auto; white-space: pre-wrap;
  }
  .log-entry-system { color: #858585; }
  .log-entry-prompt { color: #4ec9b0; font-weight: bold; }
  .log-entry-cmd { color: #00ff66; font-weight: bold; }
  .log-entry-exp { color: #ce9178; }
  .log-entry-stdout { color: #d4d4d4; }
  .log-entry-stderr { color: #f14c4c; }
  .input-bar { display: flex; gap: 8px; }
  .prompt-input {
    flex: 1; background-color: #0d0d0d; border: 1px solid #333; color: #d4d4d4;
    padding: 10px; font-family: inherit; font-size: 13px; border-radius: 2px;
  }
  .submit-btn {
    background-color: #0e639c; color: #fff; border: none; padding: 10px 16px;
    font-family: inherit; font-size: 12px; border-radius: 2px; cursor: pointer;
  }
  .submit-btn:hover { background-color: #1177bb; }
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    align-items: center; justify-content: center;
  }
  .modal-box { width: 420px; background-color: #252526; border: 1px solid #333; padding: 20px; border-radius: 4px; }
  .modal-title { font-size: 13px; font-weight: bold; color: #fff; margin-bottom: 10px; }
  .modal-sub { font-size: 12px; color: #999; margin-bottom: 12px; }
  .cmd-box { background-color: #0d0d0d; border: 1px solid #333; padding: 10px; font-size: 12px; color: #00ff66; border-radius: 2px; white-space: pre-wrap; margin-bottom: 10px; }
  .exp-box { background-color: #1e1e1e; border: 1px solid #333; padding: 10px; font-size: 12px; color: #ce9178; border-radius: 2px; margin-bottom: 4px; }
  .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 12px; }
  .btn-cancel { background-color: #3a3d41; color: #fff; border: none; padding: 8px 14px; font-family: inherit; font-size: 12px; cursor: pointer; border-radius: 2px; }
  .btn-cancel:hover { background-color: #4e5257; }
  .btn-approve { background-color: #238636; color: #fff; border: none; padding: 8px 16px; font-family: inherit; font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 2px; }
  .btn-approve:hover { background-color: #2ea043; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-title">⚡ CODE EDITOR AGENT</div>
    <div class="header-right">
      <div class="presence-badge" id="presenceBadge">1 online</div>
      <div class="room-badge" id="roomBadge" onclick="copyRoomCode()" title="Click to copy">ROOM: __ROOM_ID__</div>
    </div>
  </div>
  <div class="workspace">
    <div class="sidebar">
      <div class="sidebar-section-title">Command Templates</div>
      <button class="template-btn" onclick="setPrompt('Create a main.py file with a print statement')">Create main.py file</button>
      <button class="template-btn" onclick="setPrompt('List all files in the directory')">List directory files</button>
      <button class="template-btn" onclick="setPrompt('Find all .py files')">Find python files</button>
      <button class="template-btn" onclick="setPrompt('Show disk space usage')">Check disk usage</button>
      <button class="template-btn" onclick="setPrompt('Create a folder named data')">Create data folder</button>
      <div class="sidebar-row">
        <div class="sidebar-section-title">Files</div>
        <button class="refresh-btn" onclick="loadFiles()" title="Refresh file list">🔄</button>
      </div>
      <pre class="file-tree-container" id="fileTree">Loading files...</pre>
    </div>
    <div class="main-content">
      <div class="sidebar-section-title">Terminal Log Output</div>
      <div class="terminal-log" id="terminalLog">
<span class="log-entry-system">[SYSTEM] Room __ROOM_ID__ initialized. Share this code so others can join.</span>
<span class="log-entry-system">[SYSTEM] Commands execute strictly in this room's sandbox.</span>
----------------------------------------------------------------------
</div>
      <div class="input-bar">
        <input type="text" class="prompt-input" id="promptInput" placeholder="Type prompt (e.g. 'Create a file named test.py')..." onkeydown="if(event.key==='Enter') handlePromptSubmit()">
        <button class="submit-btn" onclick="handlePromptSubmit()">GENERATE COMMAND</button>
      </div>
    </div>
  </div>
</div>

<div class="modal-overlay" id="confirmModal">
  <div class="modal-box">
    <div class="modal-title">CONFIRM COMMAND EXECUTION</div>
    <div class="modal-sub">The AI proposed the following shell command to run in this room's sandbox:</div>
    <div class="cmd-box" id="modalCmd"></div>
    <div class="exp-box" id="modalExp"></div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeModal(false)">CANCEL</button>
      <button class="btn-approve" onclick="closeModal(true)">APPROVE & EXECUTE</button>
    </div>
  </div>
</div>

<script>
const ROOM_ID = "__ROOM_ID__";
let pendingCommand = "";
let pendingExplanation = "";

function setPrompt(text) { document.getElementById('promptInput').value = text; }

function appendLog(htmlText) {
  const log = document.getElementById('terminalLog');
  log.innerHTML += htmlText + '\\n';
  log.scrollTop = log.scrollHeight;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function copyRoomCode() {
  navigator.clipboard.writeText(ROOM_ID);
  const badge = document.getElementById('roomBadge');
  const original = badge.textContent;
  badge.textContent = 'COPIED!';
  setTimeout(() => badge.textContent = original, 1000);
}

async function loadFiles() {
  try {
    const res = await fetch('/api/' + ROOM_ID + '/files');
    const data = await res.json();
    document.getElementById('fileTree').textContent = data.tree || '(empty)';
  } catch (err) {
    document.getElementById('fileTree').textContent = 'Error loading files: ' + err;
  }
}

async function handlePromptSubmit() {
  const input = document.getElementById('promptInput');
  const prompt = input.value.trim();
  if (!prompt) return;
  input.value = '';

  appendLog(`\\n<span class="log-entry-prompt">&gt; PROMPT:</span> ${escapeHtml(prompt)}`);
  appendLog(`<span class="log-entry-system">[AI] Translating prompt via Featherless AI...</span>`);

  try {
    const res = await fetch('/api/' + ROOM_ID + '/ai-command', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prompt })
    });
    const data = await res.json();
    pendingCommand = data.command || "";
    pendingExplanation = data.explanation || "";
    document.getElementById('modalCmd').textContent = pendingCommand;
    document.getElementById('modalExp').textContent = 'Explanation: ' + pendingExplanation;
    document.getElementById('confirmModal').style.display = 'flex';
  } catch (err) {
    appendLog(`<span class="log-entry-stderr">[ERROR] AI request failed: ${escapeHtml(String(err))}</span>`);
  }
}

async function closeModal(approved) {
  document.getElementById('confirmModal').style.display = 'none';
  if (!approved) {
    appendLog(`<span class="log-entry-system">[CANCELLED] Command execution cancelled.</span>`);
    return;
  }
  try {
    await fetch('/api/' + ROOM_ID + '/execute', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: pendingCommand, explanation: pendingExplanation })
    });
    // Result and file-tree updates arrive for everyone via the websocket broadcast.
  } catch (err) {
    appendLog(`<span class="log-entry-stderr">[ERROR] Execution request failed: ${escapeHtml(String(err))}</span>`);
  }
}

// ---- Real-time sync with collaborators in the same room ----
function connectSocket() {
  const proto = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
  const ws = new WebSocket(proto + window.location.host + '/ws/' + ROOM_ID);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'execution') {
      appendLog(`\\n<span class="log-entry-cmd">[RAN by ${escapeHtml(msg.user)}]</span> ${escapeHtml(msg.command)}`);
      if (msg.explanation) appendLog(`<span class="log-entry-exp">[EXPLANATION] ${escapeHtml(msg.explanation)}</span>`);
      if (msg.stdout) appendLog(`<span class="log-entry-stdout">[STDOUT]\\n${escapeHtml(msg.stdout.trim())}</span>`);
      if (msg.stderr) appendLog(`<span class="log-entry-stderr">[STDERR]\\n${escapeHtml(msg.stderr.trim())}</span>`);
      appendLog(`<span class="log-entry-system">[EXIT CODE] ${msg.returncode}</span>`);
    } else if (msg.type === 'files') {
      document.getElementById('fileTree').textContent = msg.tree || '(empty)';
    } else if (msg.type === 'presence') {
      document.getElementById('presenceBadge').textContent = msg.count + (msg.count === 1 ? ' online' : ' online');
    }
  };

  ws.onclose = () => setTimeout(connectSocket, 2000);
}

loadFiles();
connectSocket();
</script>
</body>
</html>
"""


@app.get("/room/{room_id}", response_class=HTMLResponse)
def room_page(room_id: str):
    room_id = room_id.strip().upper()
    if not room_exists(room_id):
        return HTMLResponse(
            content=f"<body style='background:#1e1e1e;color:#f14c4c;font-family:monospace;padding:40px;'>"
                    f"Room '{room_id}' not found. <a style='color:#4ec9b0;' href='/'>Go back</a></body>",
            status_code=404,
        )
    html = ROOM_HTML_TEMPLATE.replace("__ROOM_ID__", room_id)
    return HTMLResponse(content=html)


# -----------------------------------------------------------------------------
# 8. Entrypoint for Render & local execution
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Starting Collaborative AI Code Editor Agent on port {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT, reload=False)