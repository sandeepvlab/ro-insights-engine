import json
import os
import time
import glob
import sys

# Allow importing from packages/rag, packages/observability, packages/guardrails
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "rag"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "observability"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "guardrails"))


from openai import OpenAI
from dotenv import load_dotenv
from retrieve import retrieve_relevant_chunks
from logger import new_run_id, log_event, Timer
from guardrails import scrub_ro_for_llm, enforce_action_allowed


load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CHAT_MODEL = "gpt-5-mini" 

# --- Real LLM call ---
def call_llm(prompt: str):
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an automotive repair order damage classifier. "
                    "Classify the damage using ONLY one of these categories: "
                    "MECHANICAL, ELECTRICAL, ENGINE, COLLISION, BRAKE. "
                    "Use ENGINE only for combustion/ignition-specific issues (spark plugs, ignition coils, "
                    "misfires). Use MECHANICAL for drivetrain, cooling system, turbocharger, water pump, "
                    "or other non-electrical mechanical component failures. "
                    "Given technician findings, respond ONLY with a JSON object "
                    "with keys: category, sub_category, severity, confidence. "
                    "category MUST be one of the five listed values exactly. "
                    "No extra text, no markdown fences."
        )
            },
            {"role": "user", "content": prompt}
        ]
    )
    content = response.choices[0].message.content.strip()
    content = content.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(content)
    usage = response.usage
    return parsed, usage.prompt_tokens, usage.completion_tokens


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
    enforce_action_allowed("READ_RO")
    with open(ro_path) as f:
        return json.load(f)


def classify_damage(ro: dict, run_id: str) -> dict:
    enforce_action_allowed("CLASSIFY_DAMAGE")

    # Guardrail: strip PII before any data reaches the LLM
    safe_ro = scrub_ro_for_llm(ro)


    prompt = (
        f"Customer complaint: {safe_ro['repair_concern']['customer_complaint']}\n"
        f"Technician findings: {safe_ro['repair_concern']['technician_findings']}\n"
        f"Cause: {safe_ro['repair_concern']['cause']}\n"
        f"Correction: {safe_ro['repair_concern']['correction']}"
    )

    with Timer() as t:
        try:
            result, tokens_in, tokens_out = with_retries(call_llm, 2, prompt)
        except Exception as e:
            log_event(run_id, ro["ro_id"], "CLASSIFY_DAMAGE", "FAILURE", error=str(e))
            raise

    log_event(
        run_id, ro["ro_id"], "CLASSIFY_DAMAGE", "SUCCESS",
        latency_ms=t.elapsed_ms, tokens_in=tokens_in, tokens_out=tokens_out
    )
    return result


def extract_labor_parts(ro: dict, run_id: str) -> dict:
    with Timer() as t:
        result = {
            "total_labor_amount": sum(op["amount"] for op in ro["labor"]["operations"]),
            "total_parts_amount": sum(p["sale_price"] * p["quantity"] for p in ro["parts"]),
            "submitted_labor_rate": ro["labor"]["customer_rate"]
        }
    log_event(run_id, ro["ro_id"], "EXTRACT_LABOR_PARTS", "SUCCESS", latency_ms=t.elapsed_ms)
    return result


def retrieve_warranty_rules(ro: dict, run_id: str) -> dict:
    enforce_action_allowed("RETRIEVE_WARRANTY_RULES")
    state_code = ro["state"]["state_code"]

    with Timer() as t:
        try:
            chunks = retrieve_relevant_chunks(
                query="What is the statutory or reference labor rate for warranty repairs?",
                state_code=state_code,
                top_k=1
            )
        except Exception as e:
            log_event(run_id, ro["ro_id"], "RETRIEVE_WARRANTY_RULES", "FAILURE", error=str(e))
            raise

    if not chunks:
        log_event(run_id, ro["ro_id"], "RETRIEVE_WARRANTY_RULES", "SUCCESS",
                   latency_ms=t.elapsed_ms, extra={"found_chunks": 0})
        return {"reference_labor_rate": None, "source_chunk": None}

    state_reference_rates = {"WA": 165.0, "OR": 160.0}

    log_event(run_id, ro["ro_id"], "RETRIEVE_WARRANTY_RULES", "SUCCESS",
              latency_ms=t.elapsed_ms, extra={"found_chunks": len(chunks), "state": state_code})

    return {
        "reference_labor_rate": state_reference_rates.get(state_code),
        "source_chunk": chunks[0]["chunk_text"]
    }


def compute_uplift_opportunities(ro: dict, labor_parts: dict, rules: dict, run_id: str) -> list:
    enforce_action_allowed("COMPUTE_UPLIFT")
    opportunities = []
    reason = None

    with Timer() as t:
        eligible_classifications = {"WARRANTY", "EXTENDED_WARRANTY"}
        if ro["payment_classification"] not in eligible_classifications:
            reason = "not_warranty_classification"
        elif ro["warranty"]["coverage_status"] != "ELIGIBLE":
            reason = "not_coverage_eligible"
        else:
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

    
    log_extra = {"opportunities_found": len(opportunities)}
    if reason:
        log_extra["reason"] = reason
    log_event(run_id, ro["ro_id"], "COMPUTE_UPLIFT", "SUCCESS",
              latency_ms=t.elapsed_ms, extra=log_extra)

    return opportunities


def needs_approval(opportunities: list) -> bool:
    return any(op.get("potential_additional_labor", 0) > 50 for op in opportunities)


# --- Orchestrator ---
def run_pipeline(ro_path: str) -> dict:
    run_id = new_run_id()
    print(f"\n=== Processing {ro_path} (run_id={run_id}) ===")

    ro = load_ro(ro_path)
    log_event(run_id, ro["ro_id"], "LOAD_RO", "SUCCESS")
    print("  [state] LOAD_RO -> done")

    damage = classify_damage(ro, run_id)
    print(f"  [state] CLASSIFY_DAMAGE -> {damage}")

    labor_parts = extract_labor_parts(ro, run_id)
    print(f"  [state] EXTRACT_LABOR_PARTS -> {labor_parts}")

    rules = retrieve_warranty_rules(ro, run_id)
    print(f"  [state] RETRIEVE_WARRANTY_RULES -> reference_rate={rules['reference_labor_rate']}")

    opportunities = compute_uplift_opportunities(ro, labor_parts, rules, run_id)
    print(f"  [state] COMPUTE_UPLIFT -> {opportunities}")

    approval_required = needs_approval(opportunities)
    status = "NEEDS_APPROVAL" if approval_required else "DONE"
    log_event(run_id, ro["ro_id"], "PIPELINE_COMPLETE", status)
    print(f"  [state] {status}")

    return {
        "ro_id": ro["ro_id"],
        "run_id": run_id,
        "damage_classification": damage,
        "opportunities": opportunities,
        "status": status
    }


if __name__ == "__main__":
    ro_files = glob.glob("data/sample-ros/*.json")
    for ro_file in sorted(ro_files):
        result = run_pipeline(ro_file)
        print(json.dumps(result, indent=2))