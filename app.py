"""
Minimal Dark-Mode Code Editor / AI Shell Agent
================================================
A single-file NiceGUI application that presents a plain, terminal-like
interface. Natural language prompts are translated into shell commands
by an AI model (via Featherless AI's OpenAI-compatible API), shown to
the user for approval, and then executed inside a sandboxed local
"./workshop" directory.

Run locally:
    export FEATHERLESS_API_KEY=your_key_here
    python app.py

Deploy to Render:
    Start command: python app.py
    (Render sets the PORT environment variable automatically.)
"""

import json
import os
import shlex
import subprocess
from pathlib import Path

from nicegui import ui
from openai import OpenAI

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", 8080))

FEATHERLESS_API_KEY = os.environ.get("FEATHERLESS_API_KEY", "")
FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
FEATHERLESS_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"

WORKSHOP_DIR = Path(__file__).parent / "workshop"
WORKSHOP_DIR.mkdir(parents=True, exist_ok=True)
WORKSHOP_DIR = WORKSHOP_DIR.resolve()

client = None
if FEATHERLESS_API_KEY:
    client = OpenAI(base_url=FEATHERLESS_BASE_URL, api_key=FEATHERLESS_API_KEY)

SYSTEM_PROMPT = f"""You are a shell command assistant for a sandboxed workspace.
The user will describe what they want to do in natural language.
You must translate this into a single, precise, POSIX shell command that
accomplishes it, using only relative paths inside the current directory.

Rules:
- The command will be executed with cwd already set to the sandbox folder.
  Never reference or attempt to leave that folder (no absolute paths,
  no "..", no "cd /", no "sudo", no network calls).
- Prefer simple, common, non-destructive commands (ls, cat, mkdir, touch,
  find, grep, echo, cp, mv, rm on files inside the folder, etc).
- Respond with STRICT JSON only, no markdown fences, no extra prose,
  in exactly this shape:
  {{"command": "<the shell command>", "explanation": "<1-2 sentence explanation>"}}
"""

# --------------------------------------------------------------------------
# Templates shown in the sidebar
# --------------------------------------------------------------------------

COMMAND_TEMPLATES = [
    "Create a new file called notes.txt",
    "List all files in the current directory",
    "Find all python files",
    "Show the contents of app.py",
    "Create a folder named data",
    "Delete the file notes.txt",
]

# --------------------------------------------------------------------------
# Safety checks
# --------------------------------------------------------------------------

DANGEROUS_TOKENS = [
    "sudo", "rm -rf /", "rm -rf /*", " / ", "..", "~", "curl", "wget",
    ">/dev", "mkfs", "dd if=", ":(){", "shutdown", "reboot", "chmod -r 777",
]


def is_command_safe(command: str) -> tuple[bool, str]:
    """A lightweight guard against obvious sandbox-escape / destructive commands."""
    lowered = command.lower()
    for token in DANGEROUS_TOKENS:
        if token in lowered:
            return False, f"Command blocked: contains disallowed pattern '{token}'."
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return False, f"Command blocked: could not parse ({exc})."
    for part in parts:
        if part.startswith("/") or part.startswith("~"):
            return False, "Command blocked: absolute/home paths are not allowed."
        if ".." in part:
            return False, "Command blocked: parent directory traversal is not allowed."
    return True, ""


# --------------------------------------------------------------------------
# AI translation
# --------------------------------------------------------------------------

def ask_ai_for_command(user_prompt: str) -> dict:
    """Call the Featherless AI model and parse the JSON command/explanation."""
    if client is None:
        raise RuntimeError(
            "FEATHERLESS_API_KEY is not set. Export it before starting the app."
        )

    response = client.chat.completions.create(
        model=FEATHERLESS_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=300,
    )

    raw_text = response.choices[0].message.content.strip()

    # Strip accidental markdown code fences if the model adds them anyway.
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI did not return valid JSON: {raw_text!r}") from exc

    if "command" not in data or "explanation" not in data:
        raise ValueError(f"AI response missing required keys: {data!r}")

    return data


# --------------------------------------------------------------------------
# Command execution
# --------------------------------------------------------------------------

def run_command_in_workshop(command: str) -> str:
    """Execute a shell command with cwd locked to the workshop sandbox."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSHOP_DIR),
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr
        if not output:
            output = f"(no output, exit code {result.returncode})"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 20 seconds."
    except Exception as exc:  # noqa: BLE001
        return f"Error running command: {exc}"


def list_workshop_files() -> str:
    """Plain text listing of files inside the workshop folder."""
    entries = sorted(WORKSHOP_DIR.rglob("*"))
    if not entries:
        return "(workshop is empty)"
    lines = []
    for entry in entries:
        rel = entry.relative_to(WORKSHOP_DIR)
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{rel}{suffix}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

ui.colors(primary="#3a3a3a")

terminal_log_text = "workshop ready. type a request below.\n"
pending_command = {"command": "", "explanation": ""}

editor_style = (
    "background-color:#1e1e1e;color:#d4d4d4;"
    "font-family:'Courier New', monospace; font-size:13px;"
)

with ui.column().classes("w-full h-screen no-wrap").style(
    "background-color:#1e1e1e; padding:0; margin:0;"
):
    ui.label("workshop — minimal ai shell").style(
        "color:#d4d4d4; font-family:monospace; font-size:14px; "
        "padding:8px 12px; border-bottom:1px solid #333; background-color:#252526;"
    )

    with ui.row().classes("w-full flex-grow no-wrap").style("gap:0;"):

        # ---------------- Sidebar ----------------
        with ui.column().style(
            "width:260px; min-width:260px; height:100%; "
            "background-color:#252526; border-right:1px solid #333; "
            "padding:10px; overflow-y:auto;"
        ):
            ui.label("COMMAND TEMPLATES").style(
                "color:#858585; font-family:monospace; font-size:11px; letter-spacing:1px;"
            )

            template_input_ref = {"input": None}

            def use_template(text: str):
                if template_input_ref["input"] is not None:
                    template_input_ref["input"].value = text

            for template in COMMAND_TEMPLATES:
                ui.button(
                    template,
                    on_click=lambda t=template: use_template(t),
                ).props("flat dense align=left no-caps").style(
                    "color:#d4d4d4; font-family:monospace; font-size:12px; "
                    "width:100%; justify-content:flex-start; text-align:left; "
                    "background-color:#2d2d2d; margin-bottom:4px; border-radius:2px;"
                )

            ui.separator().style("background-color:#333; margin:12px 0;")

            ui.label("WORKSHOP FILES").style(
                "color:#858585; font-family:monospace; font-size:11px; letter-spacing:1px;"
            )
            file_list_label = ui.label(list_workshop_files()).style(
                "color:#9cdcfe; font-family:monospace; font-size:12px; "
                "white-space:pre-wrap; margin-top:6px;"
            )

        # ---------------- Main panel ----------------
        with ui.column().classes("flex-grow").style(
            "height:100%; padding:10px; gap:8px;"
        ):
            ui.label("TERMINAL OUTPUT").style(
                "color:#858585; font-family:monospace; font-size:11px; letter-spacing:1px;"
            )

            terminal_box = ui.textarea(value=terminal_log_text).props(
                "readonly outlined"
            ).style(
                editor_style + "width:100%; height:100%; flex-grow:1; "
                "border:1px solid #333; resize:none;"
            )

            with ui.row().classes("w-full").style("gap:8px; align-items:center;"):
                prompt_input = ui.input(
                    placeholder="Describe what you want to do, e.g. 'create a folder named data'"
                ).props("outlined dense").style(
                    editor_style + "flex-grow:1; border:1px solid #333;"
                )
                template_input_ref["input"] = prompt_input

                submit_button = ui.button("Submit").props("no-caps").style(
                    "background-color:#2d2d2d; color:#d4d4d4; font-family:monospace;"
                )


def append_terminal(text: str):
    global terminal_log_text
    terminal_log_text += text.rstrip("\n") + "\n"
    terminal_box.value = terminal_log_text


def refresh_file_list():
    file_list_label.text = list_workshop_files()


# ---------------- Confirmation dialog ----------------

with ui.dialog() as confirm_dialog, ui.card().style(
    "background-color:#252526; border:1px solid #333; min-width:400px;"
):
    ui.label("Confirm command execution").style(
        "color:#d4d4d4; font-family:monospace; font-weight:bold;"
    )
    confirm_command_label = ui.label("").style(
        "color:#4ec9b0; font-family:monospace; font-size:13px; "
        "white-space:pre-wrap; margin-top:8px;"
    )
    confirm_explanation_label = ui.label("").style(
        "color:#9cdcfe; font-family:monospace; font-size:12px; margin-top:4px;"
    )
    with ui.row().style("margin-top:16px; gap:8px; justify-content:flex-end; width:100%;"):
        cancel_btn = ui.button("Cancel").props("flat no-caps").style(
            "color:#d4d4d4; font-family:monospace;"
        )
        approve_btn = ui.button("Approve & Run").props("no-caps").style(
            "background-color:#0e639c; color:white; font-family:monospace;"
        )


def on_cancel():
    append_terminal("(command cancelled by user)")
    confirm_dialog.close()


def on_approve():
    command = pending_command["command"]
    confirm_dialog.close()
    append_terminal(f"$ {command}")
    output = run_command_in_workshop(command)
    append_terminal(output)
    refresh_file_list()


cancel_btn.on("click", on_cancel)
approve_btn.on("click", on_approve)


def handle_submit():
    user_prompt = prompt_input.value.strip()
    if not user_prompt:
        return
    prompt_input.value = ""
    append_terminal(f"> {user_prompt}")

    try:
        ai_result = ask_ai_for_command(user_prompt)
    except Exception as exc:  # noqa: BLE001
        append_terminal(f"AI error: {exc}")
        return

    command = ai_result.get("command", "").strip()
    explanation = ai_result.get("explanation", "").strip()

    if not command:
        append_terminal("AI did not return a command.")
        return

    safe, reason = is_command_safe(command)
    if not safe:
        append_terminal(f"{reason}\nProposed command: {command}")
        return

    pending_command["command"] = command
    pending_command["explanation"] = explanation
    confirm_command_label.text = f"$ {command}"
    confirm_explanation_label.text = explanation
    confirm_dialog.open()


submit_button.on("click", handle_submit)
prompt_input.on("keydown.enter", handle_submit)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=PORT,
        title="workshop — minimal ai shell",
        dark=True,
        reload=False,
    )
