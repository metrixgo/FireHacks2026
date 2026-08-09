"""The investigation loop with step-by-step reasoning model.

The agent now works as a reasoning model that:
1. Plans out investigation steps before execution
2. Executes each step with clear reasoning
3. Generates visualization blocks where appropriate
4. Reaches conclusions through multi-step analysis
"""
import json
import os
import time

from llm import _sem, client
from tools import REGISTRY, TOOL_SCHEMAS

AGENT_MODEL = os.environ.get("AGENT_MODEL", "Qwen/Qwen3-32B")
MAX_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "12"))

PLANNING_SYSTEM = """You are a safety investigation planning expert. Your task is to create a step-by-step investigation plan to answer the user's question.

Given the user's question, you must:
1. Break down the question into 3-6 logical investigation steps
2. Each step should have a clear purpose and expected outcome
3. Steps should build upon each other to reach a conclusion
4. Include data visualization steps where appropriate (graphs, charts)
5. Plan should be specific and actionable

Format your response as a JSON array of steps with this structure:
[
  {
    "step_number": 1,
    "purpose": "What this step will accomplish",
    "reasoning": "Why this step is necessary for the investigation",
    "expected_outcome": "What data/insight we expect to gain",
    "visualization": "What type of graph/chart if applicable (or 'none')"
  }
]

Example for "Which airport is safer, A or B?":
[
  {
    "step_number": 1,
    "purpose": "Get incident clusters for both airports",
    "reasoning": "Need to understand what types of safety issues exist at each airport",
    "expected_outcome": "List of failure modes and their frequencies at both airports",
    "visualization": "bar chart comparing cluster frequencies"
  },
  {
    "step_number": 2,
    "purpose": "Calculate recent trends for major clusters",
    "reasoning": "Need to see if safety issues are increasing or decreasing over time",
    "expected_outcome": "Trend statistics and rate ratios for key failure modes",
    "visualization": "line chart showing trends over time"
  },
  {
    "step_number": 3,
    "purpose": "Compare against national baseline",
    "reasoning": "Need to determine if patterns are local or national",
    "expected_outcome": "Assessment of whether issues are airport-specific",
    "visualization": "comparison chart with national averages"
  }
]

Return ONLY the JSON array, no other text."""

REASONING_SYSTEM = """You are a safety investigation reasoning expert. Your task is to:

1. Execute the planned investigation step by step
2. Provide clear reasoning for each step's purpose
3. Interpret the results and explain their significance
4. Generate appropriate visualizations when data warrants it
5. Build toward a definitive conclusion

For each step:
- Explain WHY you're taking this action
- Interpret WHAT the results mean
- Explain HOW this moves the investigation forward
- Suggest the next logical step

Always ground your reasoning in the actual data returned by tools. Never speculate beyond what the data shows.

Key reasoning principles:
- Compare relative rates, not just absolute counts
- Consider statistical significance (p-values, confidence)
- Look for patterns across multiple data sources
- Distinguish correlation from causation
- Consider operational context (airport layout, traffic volume)"""

CONCLUSION_SYSTEM = """You are a safety investigation conclusion expert. Your task is to:

1. Synthesize findings from all investigation steps
2. Provide a clear, data-driven answer to the original question
3. Support your conclusion with specific evidence from each step
4. Acknowledge limitations and uncertainties
5. Provide actionable recommendations if appropriate

Structure your conclusion:
- Direct answer to the question
- Key evidence supporting the answer
- Counter-evidence or limitations
- Overall confidence level
- Next steps or recommendations

Be concise but thorough. Base everything on the actual investigation results."""


async def create_investigation_plan(question: str) -> list:
    """Create a step-by-step investigation plan using AI planning."""
    async with _sem:
        try:
            resp = await client.chat.completions.create(
                model=AGENT_MODEL,
                messages=[
                    {"role": "system", "content": PLANNING_SYSTEM},
                    {"role": "user", "content": f"Create an investigation plan for this question: {question}"}
                ],
                max_tokens=800,
                temperature=0.3
            )
            
            content = resp.choices[0].message.content or ""
            # Try to parse JSON from the response
            try:
                # Remove markdown code blocks if present
                if "```" in content:
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()
                
                plan = json.loads(content)
                if isinstance(plan, list):
                    return plan
                else:
                    # Fallback to default plan if parsing fails
                    return create_default_plan(question)
            except json.JSONDecodeError:
                return create_default_plan(question)
                
        except Exception as e:
            print(f"Planning failed: {e}")
            return create_default_plan(question)


def create_default_plan(question: str) -> list:
    """Create a default investigation plan if AI planning fails."""
    return [
        {
            "step_number": 1,
            "purpose": "Gather baseline data",
            "reasoning": "Need to establish the current state before analysis",
            "expected_outcome": "Basic statistics and incident data",
            "visualization": "none"
        },
        {
            "step_number": 2,
            "purpose": "Analyze patterns and trends",
            "reasoning": "Identify significant patterns in the data",
            "expected_outcome": "Trend analysis and statistical measures",
            "visualization": "trend chart"
        },
        {
            "step_number": 3,
            "purpose": "Compare and contextualize",
            "reasoning": "Compare against baselines to understand significance",
            "expected_outcome": "Comparative analysis and context",
            "visualization": "comparison chart"
        }
    ]


async def execute_step_with_reasoning(step_plan: dict, context: list, emit) -> dict:
    """Execute a single investigation step with AI reasoning."""
    step_num = step_plan["step_number"]
    purpose = step_plan["purpose"]
    reasoning = step_plan["reasoning"]
    
    # Emit the step plan with reasoning
    await emit("step_plan", {
        "step_number": step_num,
        "purpose": purpose,
        "reasoning": reasoning,
        "expected_outcome": step_plan["expected_outcome"],
        "visualization": step_plan["visualization"]
    })
    
    # Build context message for AI reasoning
    context_summary = "\n".join([
        f"Step {ctx.get('step', '?')}: {ctx.get('purpose', '')} - {ctx.get('result_summary', '')}"
        for ctx in context[-3:]  # Last 3 steps for context
    ])
    
    # Ask AI to decide what tool to call for this step
    reasoning_prompt = f"""Step {step_num}: {purpose}
Reasoning: {reasoning}
Expected: {step_plan['expected_outcome']}

Previous context:
{context_summary}

Based on this step's purpose and the investigation context, what tool should I call next?
Respond with the tool name and arguments in JSON format: {{"tool": "tool_name", "args": {{"arg": "value"}}}}
If no tool is needed for this step, respond with {{"tool": "none", "reasoning": "explanation"}}"""

    async with _sem:
        try:
            resp = await client.chat.completions.create(
                model=AGENT_MODEL,
                messages=[
                    {"role": "system", "content": REASONING_SYSTEM},
                    {"role": "user", "content": reasoning_prompt}
                ],
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=500,
                temperature=0.3
            )
            
            msg = resp.choices[0].message
            
            # Check if AI wants to use a tool
            if msg.tool_calls:
                for call in msg.tool_calls:
                    tool_name = call.function.name
                    try:
                        tool_args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    await emit("tool_call", {
                        "step": step_num,
                        "name": tool_name,
                        "args": tool_args,
                        "reasoning": f"Executing {tool_name} to: {purpose}"
                    })
                    
                    # Execute the tool
                    fn = REGISTRY.get(tool_name)
                    if fn is None:
                        result = {"error": f"no such tool: {tool_name}"}
                    else:
                        try:
                            result = await fn(**tool_args)
                        except Exception as e:
                            result = {"error": f"{type(e).__name__}: {e}"}
                    
                    await emit("tool_result", {
                        "step": step_num,
                        "name": tool_name,
                        "result": result
                    })
                    
                    # Generate AI interpretation of the result
                    interpretation = await interpret_result(tool_name, result, purpose)
                    await emit("step_reasoning", {
                        "step": step_num,
                        "interpretation": interpretation,
                        "next_step_suggestion": suggest_next_step(result, step_plan)
                    })
                    
                    return {
                        "step": step_num,
                        "tool": tool_name,
                        "result": result,
                        "interpretation": interpretation,
                        "purpose": purpose
                    }
            else:
                # No tool called, provide reasoning only
                await emit("step_reasoning", {
                    "step": step_num,
                    "interpretation": msg.content or f"Step {step_num} completed without tool execution",
                    "next_step_suggestion": "Proceed to next planned step"
                })
                
                return {
                    "step": step_num,
                    "tool": "none",
                    "result": {},
                    "interpretation": msg.content,
                    "purpose": purpose
                }
                
        except Exception as e:
            await emit("error", {
                "step": step_num,
                "error": f"Step execution failed: {str(e)}"
            })
            return {
                "step": step_num,
                "error": str(e),
                "purpose": purpose
            }


async def interpret_result(tool_name: str, result: dict, purpose: str) -> str:
    """Generate AI interpretation of a tool result."""
    try:
        resp = await client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[
                {"role": "system", "content": REASONING_SYSTEM},
                {"role": "user", "content": f"""
Tool: {tool_name}
Purpose: {purpose}
Result: {json.dumps(result, indent=2)}

Interpret what this result means for the investigation. How does this move us toward answering the question? Keep it concise (2-3 sentences)."""
                }
            ],
            max_tokens=250,
            temperature=0.3
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"Interpretation failed: {str(e)}"


def suggest_next_step(result: dict, current_step: dict) -> str:
    """Suggest the next logical step based on current result."""
    if "error" in result:
        return "Review error and adjust approach"
    
    # Check if we have visualization data (multiple chart types)
    has_charts = any(result.get(key) for key in ["chart_base64", "trend_chart_base64", "comparison_chart_base64"])
    if has_charts:
        return "Analyze the generated visualization(s) and proceed to comparison"
    
    # Check if we have statistical data
    if "statistics" in result or "rate_ratio" in result or "p_value" in result:
        return "Compare these statistics against baseline or generate visualization"
    
    # Check if we have risk statistics
    if "severity_stats" in result or "category_breakdown" in result:
        return "Analyze risk patterns and generate trend visualization"
    
    # Default suggestion
    return "Proceed to next planned investigation step"


async def generate_conclusion(question: str, investigation_results: list) -> str:
    """Generate final conclusion based on all investigation steps."""
    try:
        # Build summary of investigation
        investigation_summary = "\n\n".join([
            f"Step {r.get('step', '?')} ({r.get('purpose', 'Unknown')}): {r.get('interpretation', 'No interpretation')}"
            for r in investigation_results
        ])
        
        resp = await client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[
                {"role": "system", "content": CONCLUSION_SYSTEM},
                {"role": "user", "content": f"""
Original Question: {question}

Investigation Steps Summary:
{investigation_summary}

Based on this investigation, provide a comprehensive conclusion that directly answers the question."""
                }
            ],
            max_tokens=600,
            temperature=0.3
        )
        return resp.choices[0].message.content or "Unable to generate conclusion"
    except Exception as e:
        return f"Conclusion generation failed: {str(e)}"


async def run(question: str, emit) -> None:
    """Main reasoning model execution with step-by-step investigation planning."""
    t0 = time.time()
    investigation_results = []
    
    try:
        # Step 1: Create investigation plan
        await emit("planning", {"status": "creating_plan", "question": question})
        investigation_plan = await create_investigation_plan(question)
        
        await emit("plan_created", {
            "steps": len(investigation_plan),
            "plan": investigation_plan
        })
        
        # Step 2: Execute each planned step
        for step_plan in investigation_plan:
            if len(investigation_results) >= MAX_STEPS:
                await emit("warning", {
                    "message": f"Reached maximum steps ({MAX_STEPS}), stopping investigation"
                })
                break
            
            step_result = await execute_step_with_reasoning(step_plan, investigation_results, emit)
            investigation_results.append(step_result)
        
        # Step 3: Generate conclusion
        await emit("concluding", {"status": "generating_conclusion"})
        conclusion = await generate_conclusion(question, investigation_results)
        
        await emit("answer", {
            "text": conclusion,
            "steps": len(investigation_results),
            "seconds": round(time.time() - t0, 1),
            "investigation_plan": investigation_plan,
            "step_results": investigation_results
        })
        
    except Exception as e:
        await emit("error", {
            "error": f"Investigation failed: {str(e)}",
            "steps": len(investigation_results),
            "seconds": round(time.time() - t0, 1)
        })

