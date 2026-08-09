"""The investigation loop.

The agent decides which tools to call and in what order. It cannot compute anything
itself — every quantity in its answer has to come back from a tool result.
"""
import json
import os
import time

from llm import _sem, client
from tools import REGISTRY, TOOL_SCHEMAS

AGENT_MODEL = os.environ.get("AGENT_MODEL", "Qwen/Qwen3-32B")
MAX_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "12"))

SYSTEM = """You are a safety analyst investigating aviation near-miss reports.

Your role is to EXPLAIN what the Python statistics mean in plain language. The Python tools compute all the numbers - you interpret them for the user.

Method, in order:
1. Look at what clusters exist at the airport (cluster_incidents). Explain what the clusters represent.
2. Pick the one or two most concerning and measure them (compute_trend). Explain what the rate ratio, p-value, and trend mean in plain English.
3. Always check whether it is local or national (compare_baseline). Explain whether this is a local risk or reporting artifact.
4. Read two or three underlying reports (search_reports, extract_causal_chain). Explain what the causal chains show.
5. Check plausibility against the field's layout (get_airport_context). Explain why the pattern makes sense at this airport.
6. Before answering, call verify_finding on your one-sentence conclusion.

Hard rules:
- Never state a count, rate, ratio, p-value or date that did not come back from a tool.
- Always explain what each statistic MEANS, not just what it IS. For example: "A rate ratio of 4.4 means this pattern is 4.4 times more common recently than before."
- If the trend is not significant, explain what that means: "The p-value of 0.15 means this could be random variation, not a real pattern."
- Quote at most a short phrase from any report. Summarise instead.
- After each tool call, provide a clear explanation of what the result means for the investigation.
- Finish with a short written finding: what is rising, how fast, why it is plausible, which reports show it, and what the verifier said.
"""


async def run(question: str, emit) -> None:
    """emit(event_type, payload) is awaited for each step so the UI can stream."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": question}]
    t0 = time.time()

    for step in range(MAX_STEPS):
        async with _sem:
            resp = await client.chat.completions.create(
                model=AGENT_MODEL, messages=messages, tools=TOOL_SCHEMAS,
                tool_choice="auto", max_tokens=1200, temperature=0.3)

        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            await emit("answer", {"text": msg.content or "(no answer)",
                                  "steps": step, "seconds": round(time.time() - t0, 1)})
            return

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            await emit("tool_call", {"step": step + 1, "name": name, "args": args})

            fn = REGISTRY.get(name)
            if fn is None:
                result = {"error": f"no such tool: {name}"}
            else:
                try:
                    result = await fn(**args)
                except TypeError as e:
                    result = {"error": f"bad arguments: {e}"}
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}

            await emit("tool_result", {"step": step + 1, "name": name, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result)[:12000]})
            
            # Get AI explanation of what this result means
            async with _sem:
                explanation_resp = await client.chat.completions.create(
                    model=AGENT_MODEL, 
                    messages=[
                        {"role": "system", "content": "You are a safety analyst. Explain what this tool result means in plain English. Focus on interpreting the statistics and their significance for the investigation. Keep it concise (2-3 sentences max)."},
                        {"role": "user", "content": f"Tool: {name}\nResult: {json.dumps(result, indent=2)}\n\nExplain what this result means:"}
                    ],
                    max_tokens=200, temperature=0.3)
            
            explanation = explanation_resp.choices[0].message.content or ""
            await emit("explanation", {"step": step + 1, "name": name, "text": explanation})

    await emit("answer", {"text": "Stopped after the maximum number of investigation steps "
                                  "without reaching a conclusion. Try a narrower question.",
                          "steps": MAX_STEPS, "seconds": round(time.time() - t0, 1)})

