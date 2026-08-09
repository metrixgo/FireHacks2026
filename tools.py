"""The tools the agent can call.

House rule, and it is the whole safety argument of this project:

    Every number returned to the user is computed by Python from the database.
    Models read narratives, name patterns, and write prose. Models never produce
    a statistic, a count, a rate, or a date.

compute_trend / compare_baseline / backtest_asof contain no model calls at all.
"""
import base64
import io
import json
import math
import os
from collections import Counter
from typing import List, Dict

import db
from llm import complete

# Try to import matplotlib for visualization, fallback gracefully
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

MAX_ROWS = 400


# ---------------------------------------------------------------- statistics

def _binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p). Exact, no scipy."""
    if n == 0:
        return 1.0
    k = max(0, min(k, n))
    total = 0.0
    logp, logq = math.log(max(p, 1e-12)), math.log(max(1 - p, 1e-12))
    for i in range(k, n + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                          + i * logp + (n - i) * logq)
    return min(1.0, total)


def _slope(counts):
    """Least-squares slope of monthly counts, in reports per month."""
    n = len(counts)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(counts) / n
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, counts)) / den


def _month_range(end_ym: str, months: int):
    y, m = int(end_ym[:4]), int(end_ym[5:7])
    out = []
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _latest_ym(con) -> str:
    r = con.execute("SELECT MAX(ym) AS m FROM reports").fetchone()
    return r["m"] or "1970-01"


def _series(con, cluster_id, airport, window):
    rows = con.execute(
        "SELECT ym, COUNT(*) n FROM reports WHERE cluster_id=? AND airport=? "
        f"AND ym IN ({','.join('?' * len(window))}) GROUP BY ym",
        [cluster_id, airport, *window]).fetchall()
    counts = {r["ym"]: r["n"] for r in rows}
    return [counts.get(ym, 0) for ym in window]


def _trend_core(con, cluster_id, airport, end_ym, months, recent_months):
    window = _month_range(end_ym, months)
    counts = _series(con, cluster_id, airport, window)
    recent, baseline = counts[-recent_months:], counts[:-recent_months]
    n_rec, n_base = sum(recent), sum(baseline)
    rate_rec = n_rec / max(1, len(recent))
    rate_base = n_base / max(1, len(baseline))
    total, p0 = n_rec + n_base, len(recent) / months
    p_value = _binom_tail(n_rec, total, p0)
    return {
        "cluster_id": cluster_id,
        "airport": airport,
        "window": f"{window[0]}..{window[-1]}",
        "monthly_counts": dict(zip(window, counts)),
        "recent_months": len(recent),
        "recent_reports": n_rec,
        "recent_rate_per_month": round(rate_rec, 2),
        "baseline_rate_per_month": round(rate_base, 2),
        "rate_ratio": round(rate_rec / rate_base, 2) if rate_base > 0 else None,
        "slope_reports_per_month": round(_slope(counts), 3),
        "p_value": round(p_value, 5),
        "significant_at_0.01": p_value < 0.01,
        "note": "Counts and statistics computed in Python from the report database. "
                "No language model produced these numbers.",
    }


# ---------------------------------------------------------------- the tools

async def search_reports(query: str = "", airport: str = "", months: int = 24,
                         limit: int = 12) -> dict:
    """Full-text search over narratives, newest first."""
    con = db.connect()
    window = _month_range(_latest_ym(con), max(1, months))
    sql = ("SELECT r.report_id, r.ym, r.airport, r.aircraft, r.phase, r.cluster_id, "
           "substr(r.narrative,1,600) AS narrative FROM reports r ")
    params, where = [], [f"r.ym IN ({','.join('?' * len(window))})"]
    params += window
    if query.strip():
        sql += "JOIN reports_fts f ON f.rowid = r.id "
        where.append("reports_fts MATCH ?")
        params.append(" OR ".join(w for w in query.split() if len(w) > 2) or query)
    if airport.strip():
        where.append("r.airport = ?")
        params.append(airport.strip().upper())
    sql += "WHERE " + " AND ".join(where) + " ORDER BY r.ym DESC LIMIT ?"
    params.append(min(int(limit), 25))
    rows = [dict(r) for r in con.execute(sql, params)]
    
    return {
        "n": len(rows), 
        "reports": rows,
        "interpretation": f"Found {len(rows)} reports matching the search criteria. These are the actual safety reports filed by crews, providing real-world context for the pattern being investigated."
    }


async def cluster_incidents(airport: str, months: int = 24) -> dict:
    """What failure modes exist at this field, and how big is each."""
    con = db.connect()
    window = _month_range(_latest_ym(con), max(1, months))
    rows = con.execute(
        "SELECT r.cluster_id, c.label, c.keywords, COUNT(*) n FROM reports r "
        "LEFT JOIN clusters c ON c.cluster_id = r.cluster_id "
        f"WHERE r.airport=? AND r.ym IN ({','.join('?' * len(window))}) "
        "GROUP BY r.cluster_id ORDER BY n DESC",
        [airport.upper(), *window]).fetchall()
    total = sum(r["n"] for r in rows)
    return {
        "airport": airport.upper(), 
        "window": f"{window[0]}..{window[-1]}",
        "total_reports": total,
        "num_clusters": len(rows),
        "clusters": [dict(r) for r in rows],
        "interpretation": f"Found {len(rows)} distinct failure mode clusters at {airport.upper()} totaling {total} reports over this period. Each cluster represents a different type of safety issue."
    }


async def compute_trend(cluster_id: str, airport: str, months: int = 24,
                        recent_months: int = 6) -> dict:
    """Is this failure mode getting more common here. Pure Python."""
    con = db.connect()
    result = _trend_core(con, cluster_id, airport.upper(), _latest_ym(con),
                       max(6, int(months)), max(2, int(recent_months)))
    
    # Add interpretive context
    result["interpretation"] = {
        "rate_ratio_meaning": f"A rate ratio of {result['rate_ratio']}× means this pattern is {result['rate_ratio']} times more common in recent months compared to the baseline period.",
        "p_value_meaning": f"A p-value of {result['p_value']} {'indicates strong statistical evidence this is not random variation' if result['p_value'] < 0.01 else 'suggests this could be random variation rather than a real pattern'}.",
        "slope_meaning": f"The trend slope of {result['slope_reports_per_month']} reports/month shows {'an increasing' if result['slope_reports_per_month'] > 0 else 'a decreasing or flat'} pattern over time.",
        "significance": "statistically significant rising pattern" if result["significant_at_0.01"] else "not statistically significant"
    }
    
    return result


async def compare_baseline(cluster_id: str, airport: str, months: int = 24,
                           recent_months: int = 6) -> dict:
    """Same cluster at every other field. Separates a local signal from a national one."""
    con = db.connect()
    end = _latest_ym(con)
    others = [r["airport"] for r in con.execute(
        "SELECT DISTINCT airport FROM reports WHERE airport <> ?", [airport.upper()])]
    peers = [_trend_core(con, cluster_id, a, end, months, recent_months) for a in others]
    ratios = [p["rate_ratio"] for p in peers if p["rate_ratio"] is not None]
    target = _trend_core(con, cluster_id, airport.upper(), end, months, recent_months)
    national = round(sum(ratios) / len(ratios), 2) if ratios else None
    
    # Add interpretation
    is_local = target["rate_ratio"] and national and target["rate_ratio"] > national * 1.5
    interpretation = {
        "local_vs_national": "LOCAL RISK" if is_local else "NATIONAL PATTERN OR REPORTING ARTIFACT",
        "explanation": f"The target airport's rate ratio of {target['rate_ratio']}× is compared against a peer median of {national}×. " +
                      (f"Since the target is significantly higher than peers, this appears to be a local airport-specific risk." if is_local else 
                       f"Since peers show similar patterns, this is likely a national trend or reporting artifact, not specific to this airport."),
        "target_meaning": f"{airport.upper()} shows a {target['rate_ratio']}× increase in this pattern",
        "peer_meaning": f"Other airports show a median {national}× increase, suggesting {'this is a nationwide issue' if national > 1.2 else 'no widespread increase'}"
    }
    
    return {
        "target": {"airport": target["airport"], "rate_ratio": target["rate_ratio"],
                   "p_value": target["p_value"]},
        "peer_median_rate_ratio": national,
        "peers": sorted([{"airport": p["airport"], "rate_ratio": p["rate_ratio"]} for p in peers],
                        key=lambda x: (x["rate_ratio"] is None, -(x["rate_ratio"] or 0))),
        "interpretation": interpretation,
        "interpretation_hint": "If the target ratio is high and peers sit near 1.0, the pattern is "
                               "local. If every field rose together, it is a national or reporting "
                               "artifact, not an airport-specific risk.",
    }


async def get_airport_context(icao: str) -> dict:
    """Runway layout and known quirks, so the agent can reason about plausibility."""
    con = db.connect()
    r = con.execute("SELECT * FROM airports WHERE icao=?", [icao.upper()]).fetchone()
    if not r:
        return {"icao": icao.upper(), "found": False}
    total = con.execute("SELECT COUNT(*) c FROM reports WHERE airport=?", [icao.upper()]).fetchone()["c"]
    return {**dict(r), "found": True, "reports_on_file": total}


async def extract_causal_chain(report_id: str) -> dict:
    """Model reads one narrative and returns structured causation. No numbers."""
    con = db.connect()
    r = con.execute("SELECT report_id, narrative FROM reports WHERE report_id=?",
                    [report_id]).fetchone()
    if not r:
        return {"report_id": report_id, "found": False}
    out = await complete(
        os.environ.get("EXTRACT_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
        system="You extract causal structure from aviation safety reports. Reply with JSON only, "
               "no prose, no code fences. Keys: trigger, compounding_factors (array), "
               "what_caught_it, latent_condition. Each value is one short sentence. If the "
               "narrative does not say, use null. Never invent details.",
        user=r["narrative"][:4000], max_tokens=400)
    try:
        parsed = json.loads(out.strip().strip("`").removeprefix("json").strip())
    except Exception:
        parsed = {"raw": out[:600], "parse_error": True}
    return {"report_id": report_id, "found": True, "chain": parsed}


async def verify_finding(claim: str, report_ids: str = "") -> dict:
    """A different model family checks the claim against the actual narratives."""
    con = db.connect()
    ids = [s.strip() for s in report_ids.split(",") if s.strip()][:8]
    rows = con.execute(
        f"SELECT report_id, substr(narrative,1,700) t FROM reports WHERE report_id IN "
        f"({','.join('?' * len(ids))})", ids).fetchall() if ids else []
    evidence = "\n\n".join(f"[{r['report_id']}] {r['t']}" for r in rows) or "(no reports supplied)"
    out = await complete(
        os.environ.get("VERIFY_MODEL", "mistralai/Mistral-Small-24B-Instruct-2501"),
        system="You are an adversarial reviewer. Decide whether the CLAIM is supported by the "
               "EVIDENCE. Reply JSON only: {verdict: supported|partly|unsupported, reason: one "
               "sentence, unsupported_parts: array of strings}. Be strict. If the claim asserts a "
               "cause the reports do not state, say unsupported.",
        user=f"CLAIM:\n{claim}\n\nEVIDENCE:\n{evidence[:6000]}", max_tokens=350)
    try:
        parsed = json.loads(out.strip().strip("`").removeprefix("json").strip())
    except Exception:
        parsed = {"verdict": "unknown", "reason": out[:300]}
    return {"claim": claim, "checked_against": [r["report_id"] for r in rows], **parsed}


async def backtest_asof(cluster_id: str, airport: str, cutoff_ym: str,
                        months: int = 18, recent_months: int = 6) -> dict:
    """Recompute the trend using ONLY data before cutoff_ym. This is the honesty check."""
    con = db.connect()
    y, m = int(cutoff_ym[:4]), int(cutoff_ym[5:7])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    end = f"{y:04d}-{m:02d}"
    res = _trend_core(con, cluster_id, airport.upper(), end, months, recent_months)
    res["cutoff_ym"] = cutoff_ym
    res["data_used_through"] = end
    res["would_have_flagged"] = bool(res["significant_at_0.01"] and (res["rate_ratio"] or 0) >= 1.8)
    return res


# ---------------------------------------------------------------- risk evaluation pipeline functions

def get_database_incidents(location: str) -> List[Dict]:
    """Query the database for incidents, safety reports, and news links matching a location.
    
    Args:
        location: Location name (e.g., 'San Francisco International Airport' or ICAO code like 'KSFO')
    
    Returns:
        List of dictionaries containing incident data
    """
    con = db.connect()
    
    # Try to match by ICAO code first, then by airport name
    location_upper = location.strip().upper()
    
    # First try exact ICAO match
    rows = con.execute(
        "SELECT r.report_id, r.ym, r.airport, r.aircraft, r.phase, r.narrative, r.cluster_id, "
        "c.label as cluster_label, a.name as airport_name "
        "FROM reports r "
        "LEFT JOIN clusters c ON c.cluster_id = r.cluster_id "
        "LEFT JOIN airports a ON a.icao = r.airport "
        "WHERE r.airport = ? "
        "ORDER BY r.ym DESC "
        "LIMIT 100",
        [location_upper]
    ).fetchall()
    
    # If no exact ICAO match, try airport name search
    if not rows:
        rows = con.execute(
            "SELECT r.report_id, r.ym, r.airport, r.aircraft, r.phase, r.narrative, r.cluster_id, "
            "c.label as cluster_label, a.name as airport_name "
            "FROM reports r "
            "LEFT JOIN clusters c ON c.cluster_id = r.cluster_id "
            "LEFT JOIN airports a ON a.icao = r.airport "
            "WHERE a.name LIKE ? OR r.airport LIKE ? "
            "ORDER BY r.ym DESC "
            "LIMIT 100",
            [f"%{location}%", f"%{location_upper}%"]
        ).fetchall()
    
    incidents = [dict(row) for row in rows]
    
    # Add source links (placeholder - in production, these would come from a news API)
    for incident in incidents:
        incident["source_url"] = f"https://example.com/incident/{incident['report_id']}"
    
    return incidents


def calculate_risk_statistics(events: List[Dict]) -> Dict:
    """Compute statistical summaries and generate visualization charts.
    
    Args:
        events: List of incident dictionaries from database
    
    Returns:
        Dictionary containing:
        - total_events: Total number of events
        - severity_stats: Mean and variance of severity metrics
        - category_breakdown: Count by incident category/cluster
        - time_distribution: Monthly distribution of events
        - chart_base64: Base64-encoded risk frequency histogram (if matplotlib available)
        - chart_error: Error message if chart generation fails
        - trend_chart_base64: Base64-encoded trend line chart
        - comparison_chart_base64: Base64-encoded comparison chart
    """
    if not events:
        return {
            "total_events": 0,
            "severity_stats": {"mean": 0, "variance": 0},
            "category_breakdown": {},
            "time_distribution": {},
            "chart_base64": None,
            "trend_chart_base64": None,
            "comparison_chart_base64": None,
            "chart_error": "No events to analyze"
        }
    
    # Basic statistics
    total_events = len(events)
    
    # Category breakdown (using cluster_id as proxy for severity/category)
    category_counts = Counter(event.get("cluster_id", "unknown") for event in events)
    category_breakdown = dict(category_counts)
    
    # Time distribution (by year-month)
    time_counts = Counter(event.get("ym", "unknown") for event in events)
    time_distribution = dict(sorted(time_counts.items()))
    
    # Calculate severity proxy (using cluster frequency as severity indicator)
    cluster_freq = list(category_counts.values())
    if cluster_freq:
        severity_mean = sum(cluster_freq) / len(cluster_freq)
        severity_variance = sum((x - severity_mean) ** 2 for x in cluster_freq) / len(cluster_freq)
    else:
        severity_mean = 0
        severity_variance = 0
    
    severity_stats = {
        "mean": round(severity_mean, 2),
        "variance": round(severity_variance, 2),
        "std_dev": round(math.sqrt(severity_variance), 2) if severity_variance > 0 else 0
    }
    
    # Generate charts if matplotlib is available
    chart_base64 = None
    trend_chart_base64 = None
    comparison_chart_base64 = None
    chart_error = None
    
    if HAS_MATPLOTLIB:
        try:
            # Chart 1: Risk frequency histogram (bar chart)
            if time_distribution:
                fig, ax = plt.subplots(figsize=(10, 6))
                months = list(time_distribution.keys())
                counts = list(time_distribution.values())
                
                ax.bar(months, counts, color='steelblue', alpha=0.7)
                ax.set_xlabel('Time Period (YYYY-MM)')
                ax.set_ylabel('Number of Incidents')
                ax.set_title('Risk Frequency Distribution Over Time')
                ax.xticks(rotation=45, ha='right')
                ax.tight_layout()
                
                buffer = io.BytesIO()
                plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
                buffer.seek(0)
                chart_base64 = base64.b64encode(buffer.read()).decode('utf-8')
                plt.close(fig)
            
            # Chart 2: Trend line chart
            if time_distribution and len(time_distribution) > 1:
                fig, ax = plt.subplots(figsize=(10, 6))
                months = list(time_distribution.keys())
                counts = list(time_distribution.values())
                
                ax.plot(months, counts, marker='o', linestyle='-', color='darkblue', linewidth=2)
                ax.fill_between(months, counts, alpha=0.3, color='steelblue')
                ax.set_xlabel('Time Period (YYYY-MM)')
                ax.set_ylabel('Number of Incidents')
                ax.set_title('Incident Trend Over Time')
                ax.xticks(rotation=45, ha='right')
                ax.grid(True, alpha=0.3)
                ax.tight_layout()
                
                buffer = io.BytesIO()
                plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
                buffer.seek(0)
                trend_chart_base64 = base64.b64encode(buffer.read()).decode('utf-8')
                plt.close(fig)
            
            # Chart 3: Category comparison (bar chart)
            if category_breakdown:
                fig, ax = plt.subplots(figsize=(10, 6))
                categories = list(category_breakdown.keys())[:10]  # Top 10 categories
                values = [category_breakdown[cat] for cat in categories]
                
                ax.barh(categories, values, color='coral', alpha=0.7)
                ax.set_xlabel('Number of Incidents')
                ax.set_ylabel('Incident Category')
                ax.set_title('Incident Distribution by Category')
                ax.tight_layout()
                
                buffer = io.BytesIO()
                plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
                buffer.seek(0)
                comparison_chart_base64 = base64.b64encode(buffer.read()).decode('utf-8')
                plt.close(fig)
                
        except Exception as e:
            chart_error = f"Chart generation failed: {str(e)}"
    else:
        chart_error = "Matplotlib not available for visualization"
    
    return {
        "total_events": total_events,
        "severity_stats": severity_stats,
        "category_breakdown": category_breakdown,
        "time_distribution": time_distribution,
        "chart_base64": chart_base64,
        "trend_chart_base64": trend_chart_base64,
        "comparison_chart_base64": comparison_chart_base64,
        "chart_error": chart_error,
        "interpretation": f"Analyzed {total_events} incidents across {len(category_breakdown)} categories. "
                          f"Severity mean: {severity_stats['mean']}, variance: {severity_stats['variance']}. "
                          f"Data spans {len(time_distribution)} time periods. "
                          f"Generated {sum(bool(c) for c in [chart_base64, trend_chart_base64, comparison_chart_base64])} visualization charts."
    }


def build_featherless_prompt(location: str, stats: Dict, events: List[Dict]) -> str:
    """Construct system/user prompt forcing structured 4-block markdown response.
    
    Args:
        location: Location being analyzed
        stats: Statistical summary from calculate_risk_statistics
        events: Raw incident data from database
    
    Returns:
        Complete prompt string for Featherless AI with system and user components
    """
    # Prepare event summaries for the prompt (limit to avoid token limits)
    event_summaries = []
    for i, event in enumerate(events[:10]):  # Limit to 10 events for context
        summary = f"Event {i+1}: {event.get('ym', 'Unknown date')} - {event.get('cluster_label', event.get('cluster_id', 'Unknown category'))}"
        if event.get('narrative'):
            narrative_preview = event['narrative'][:200] + "..." if len(event['narrative']) > 200 else event['narrative']
            summary += f". Description: {narrative_preview}"
        event_summaries.append(summary)
    
    events_context = "\n".join(event_summaries) if event_summaries else "No specific event details available."
    
    # System prompt - enforces strict structure
    system_prompt = """You are a safety risk analysis expert. Your task is to evaluate aviation safety incidents and provide a structured, 4-block markdown response.

You MUST respond with exactly 4 labeled blocks in this format:

## BLOCK 1: RISK ASSESSMENT SUMMARY
[Brief 2-3 sentence summary of the overall risk level at this location]

## BLOCK 2: STATISTICAL ANALYSIS  
[Interpretation of the provided statistics: total events, severity metrics, category breakdown, time patterns]

## BLOCK 3: KEY INCIDENTS AND PATTERNS
[Analysis of the most significant incidents and recurring patterns based on the event data]

## BLOCK 4: RECOMMENDATIONS AND SOURCES
[Specific safety recommendations followed by clickable source links in the format: [Source Title](URL)]

CRITICAL REQUIREMENTS:
- Use exactly the block headers shown above
- Provide step-by-step explanations in each block
- Include clickable [Title](URL) links in Block 4
- Base all analysis on the provided statistics and event data
- Do not invent statistics or counts beyond what is provided
- Keep each block concise but informative"""

    # User prompt with data
    user_prompt = f"""LOCATION: {location}

STATISTICAL DATA:
- Total Events: {stats.get('total_events', 0)}
- Severity Mean: {stats.get('severity_stats', {}).get('mean', 0)}
- Severity Variance: {stats.get('severity_stats', {}).get('variance', 0)}
- Standard Deviation: {stats.get('severity_stats', {}).get('std_dev', 0)}
- Category Breakdown: {stats.get('category_breakdown', {})}
- Time Distribution: {stats.get('time_distribution', {})}

INTERPRETATION: {stats.get('interpretation', 'No interpretation available.')}

INCIDENT DATA ({len(events)} total events, showing first 10):
{events_context}

Source URLs format: [Incident Report ID](https://example.com/incident/{{report_id}})

Please analyze this data and provide your structured 4-block response."""

    return f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}"


async def evaluate_risk(location: str) -> Dict:
    """Main orchestrator function for risk evaluation pipeline.
    
    Args:
        location: Location name or ICAO code to evaluate
    
    Returns:
        Dictionary containing:
        - location: Evaluated location
        - incidents: Raw incident data from database
        - statistics: Computed risk statistics
        - ai_analysis: Featherless AI structured response
        - chart_data: Base64 chart if available
        - pipeline_status: Status of each pipeline stage
    """
    pipeline_status = {
        "database_query": "pending",
        "statistics_calculation": "pending", 
        "ai_analysis": "pending",
        "overall": "in_progress"
    }
    
    try:
        # Stage 1: Query database for incidents
        pipeline_status["database_query"] = "in_progress"
        incidents = get_database_incidents(location)
        pipeline_status["database_query"] = f"completed ({len(incidents)} events found)"
        
        # Stage 2: Calculate risk statistics
        pipeline_status["statistics_calculation"] = "in_progress"
        statistics = calculate_risk_statistics(incidents)
        pipeline_status["statistics_calculation"] = "completed"
        
        # Stage 3: Build Featherless prompt and get AI analysis
        pipeline_status["ai_analysis"] = "in_progress"
        featherless_prompt = build_featherless_prompt(location, statistics, incidents)
        
        try:
            # Use existing llm.complete function
            ai_response = await complete(
                model=os.environ.get("AGENT_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
                system="You are a safety risk analysis expert.",
                user=featherless_prompt,
                max_tokens=1000,
                temperature=0.3
            )
            pipeline_status["ai_analysis"] = "completed"
        except Exception as ai_error:
            ai_response = f"AI analysis failed: {str(ai_error)}. Using statistical analysis only."
            pipeline_status["ai_analysis"] = f"failed: {str(ai_error)}"
        
        pipeline_status["overall"] = "completed"
        
        return {
            "location": location,
            "incidents": incidents,
            "statistics": statistics,
            "ai_analysis": ai_response,
            "chart_data": statistics.get("chart_base64"),
            "pipeline_status": pipeline_status,
            "timestamp": _latest_ym(db.connect())
        }
        
    except Exception as e:
        pipeline_status["overall"] = f"failed: {str(e)}"
        return {
            "location": location,
            "error": str(e),
            "pipeline_status": pipeline_status,
            "incidents": [],
            "statistics": None,
            "ai_analysis": None
        }


REGISTRY = {f.__name__: f for f in [
    search_reports, cluster_incidents, compute_trend, compare_baseline,
    get_airport_context, extract_causal_chain, verify_finding, backtest_asof,
    evaluate_risk,
]}


def _schema(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


S = lambda d: {"type": "string", "description": d}
I = lambda d: {"type": "integer", "description": d}

TOOL_SCHEMAS = [
    _schema("search_reports", "Full-text search of near-miss narratives. Use this first to see "
            "what crews are actually reporting.",
            {"query": S("keywords, e.g. 'parallel runway confusion'"),
             "airport": S("ICAO like KSFO, or empty for all"),
             "months": I("lookback window, default 24"), "limit": I("max 25")}, []),
    _schema("cluster_incidents", "List the failure-mode clusters present at an airport with "
            "report counts. Use this to find candidate patterns before measuring any of them.",
            {"airport": S("ICAO"), "months": I("default 24")}, ["airport"]),
    _schema("compute_trend", "Measure whether one cluster is rising at one airport. Returns "
            "monthly counts, rate ratio and a p-value, all computed in Python.",
            {"cluster_id": S("like C03"), "airport": S("ICAO"), "months": I("default 24"),
             "recent_months": I("default 6")}, ["cluster_id", "airport"]),
    _schema("compare_baseline", "Compare the same cluster's trend at every other airport, to "
            "tell a local risk from a national reporting shift. Always call this before "
            "concluding a pattern is airport-specific.",
            {"cluster_id": S("like C03"), "airport": S("ICAO"), "months": I("default 24"),
             "recent_months": I("default 6")}, ["cluster_id", "airport"]),
    _schema("get_airport_context", "Runway layout, annual operations and known quirks for an "
            "airport. Use it to judge whether a pattern is physically plausible.",
            {"icao": S("ICAO")}, ["icao"]),
    _schema("extract_causal_chain", "Read one report and return its trigger, compounding "
            "factors, what caught it, and the latent condition.",
            {"report_id": S("report id from search_reports")}, ["report_id"]),
    _schema("verify_finding", "Have an independent model check your conclusion against the "
            "source narratives. Call this on your final finding before you answer.",
            {"claim": S("your one-sentence finding"),
             "report_ids": S("comma-separated ids that should support it")}, ["claim"]),
    _schema("backtest_asof", "Recompute a trend using only data before a cutoff month, to test "
            "whether the pattern was detectable in advance.",
            {"cluster_id": S("like C03"), "airport": S("ICAO"),
             "cutoff_ym": S("YYYY-MM, the month to pretend is 'now'"),
             "months": I("default 18"), "recent_months": I("default 6")},
            ["cluster_id", "airport", "cutoff_ym"]),
    _schema("evaluate_risk", "Complete risk evaluation pipeline for a location. Queries database, "
            "computes statistical risk metrics, generates charts, and provides AI analysis. "
            "Returns structured 4-block markdown response with risk assessment, statistical analysis, "
            "key incidents, and recommendations with clickable sources.",
            {"location": S("Airport name (e.g., 'San Francisco International Airport') or ICAO code (e.g., 'KSFO')")}, 
            ["location"]),
]

