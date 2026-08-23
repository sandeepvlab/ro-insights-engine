import json
import os
import time
import glob
import sys

# Allow importing retrieve.py from packages/rag
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "rag"))

from openai import OpenAI
from dotenv import load_dotenv
from retrieve import retrieve_relevant_chunks

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CHAT_MODEL = "gpt-4o-mini"  


# --- Real LLM call ---
def call_llm(prompt: str) -> dict:
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an automotive repair order damage classifier. "
                    "Given technician findings, respond ONLY with a JSON object "
                    "with keys: category, sub_category, severity, confidence. "
                    "No extra text, no markdown fences."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )
    content = response.choices[0].message.content.strip()
    # Defensive: strip accidental code fences if the model adds them
    content = content.replace("```json", "").replace("```", "").strip()
    return json.loads(content)


# --- Retry wrapper ---
def with_retries(func, max_attempts=2, *args, **kwargs):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            print(f"  [retry] attempt {attempt} failed: {e}")
            time.sleep(1)
    raise last_error


# --- States ---
def load_ro(ro_path: str) -> dict:
    with open(ro_path) as f:
        return json.load(f)


def classify_damage(ro: dict) -> dict:
    prompt = (
        f"Customer complaint: {ro['repair_concern']['customer_complaint']}\n"
        f"Technician findings: {ro['repair_concern']['technician_findings']}\n"
        f"Cause: {ro['repair_concern']['cause']}\n"
        f"Correction: {ro['repair_concern']['correction']}"
    )
    result = with_retries(call_llm, 2, prompt)
    return result


def extract_labor_parts(ro: dict) -> dict:
    return {
        "total_labor_amount": sum(op["amount"] for op in ro["labor"]["operations"]),
        "total_parts_amount": sum(p["sale_price"] * p["quantity"] for p in ro["parts"]),
        "submitted_labor_rate": ro["labor"]["customer_rate"]
    }


def retrieve_warranty_rules(ro: dict) -> dict:
    """
    Real RAG retrieval: pulls the most relevant warranty-rule chunk
    for this RO's state from pgvector.
    """
    state_code = ro["state"]["state_code"]
    chunks = retrieve_relevant_chunks(
        query="What is the statutory or reference labor rate for warranty repairs?",
        state_code=state_code,
        top_k=1
    )

    if not chunks:
        return {"reference_labor_rate": None, "source_chunk": None}

    # Known reference rates per state (for the demo; a fuller build would
    # extract this number directly from the retrieved chunk text via LLM)
    state_reference_rates = {"WA": 165.0, "OR": 160.0}

    return {
        "reference_labor_rate": state_reference_rates.get(state_code),
        "source_chunk": chunks[0]["chunk_text"]
    }


def compute_uplift_opportunities(ro: dict, labor_parts: dict, rules: dict) -> list:
    opportunities = []

    # Eligibility gate: only warranty-eligible ROs can have uplift opportunities
    eligible_classifications = {"WARRANTY", "EXTENDED_WARRANTY"}
    if ro["payment_classification"] not in eligible_classifications:
        return opportunities
    if ro["warranty"]["coverage_status"] != "ELIGIBLE":
        return opportunities

    submitted_rate = labor_parts["submitted_labor_rate"]
    reference_rate = rules.get("reference_labor_rate")

    if reference_rate and submitted_rate < reference_rate:
        extra_hours = ro["labor"]["total_hours"]
        opportunities.append({
            "type": "WARRANTY_LABOR_RATE",
            "finding": f"Submitted labor rate ${submitted_rate}/hr is below reference rate ${reference_rate}/hr",
            "current_rate": submitted_rate,
            "reference_rate": reference_rate,
            "potential_additional_labor": round((reference_rate - submitted_rate) * extra_hours, 2)
        })

    return opportunities


def needs_approval(opportunities: list) -> bool:
    return any(op.get("potential_additional_labor", 0) > 50 for op in opportunities)


# --- Orchestrator ---
def run_pipeline(ro_path: str) -> dict:
    print(f"\n=== Processing {ro_path} ===")

    ro = load_ro(ro_path)
    print("  [state] LOAD_RO -> done")

    damage = classify_damage(ro)
    print(f"  [state] CLASSIFY_DAMAGE -> {damage}")

    labor_parts = extract_labor_parts(ro)
    print(f"  [state] EXTRACT_LABOR_PARTS -> {labor_parts}")

    rules = retrieve_warranty_rules(ro)
    print(f"  [state] RETRIEVE_WARRANTY_RULES -> reference_rate={rules['reference_labor_rate']}")

    opportunities = compute_uplift_opportunities(ro, labor_parts, rules)
    print(f"  [state] COMPUTE_UPLIFT -> {opportunities}")

    approval_required = needs_approval(opportunities)
    status = "NEEDS_APPROVAL" if approval_required else "DONE"
    print(f"  [state] {status}")

    return {
        "ro_id": ro["ro_id"],
        "damage_classification": damage,
        "opportunities": opportunities,
        "status": status
    }


if __name__ == "__main__":
    ro_files = glob.glob("data/sample-ros/*.json")
    for ro_file in sorted(ro_files):
        result = run_pipeline(ro_file)
        print(json.dumps(result, indent=2))