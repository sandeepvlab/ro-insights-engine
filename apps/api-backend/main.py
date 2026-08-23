import os
import sys
import glob
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Allow importing the orchestrator
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "packages", "agent-orchestration"))
from orchestrator import run_pipeline

app = FastAPI(
    title="RO Insights Engine API",
    description="AI-powered Repair Order review: damage classification, warranty uplift analysis.",
    version="0.1.0",
)

# Allow the Angular dev server (or any local frontend) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for local demo; restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

RO_DIR = "data/sample-ros"

# Simple in-memory store of results, keyed by run_id.
RUN_RESULTS = {}


@app.get("/")
def root():
    return {"status": "ok", "message": "RO Insights Engine API is running"}


@app.get("/ro/list")
def list_ros():
    """List available sample Repair Order IDs that can be analyzed."""
    files = sorted(glob.glob(os.path.join(RO_DIR, "*.json")))
    ro_ids = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
            ro_ids.append({"ro_id": data["ro_id"], "file": os.path.basename(f)})
    return {"repair_orders": ro_ids}


@app.post("/ro/{ro_id}/analyze")
def analyze_ro(ro_id: str):
    """
    Run the full agent pipeline against a given RO by its ID (e.g. 'RO-001').
    Returns the run_id and full insights result.
    """
    filename = ro_id.lower().replace("ro-", "ro_") + ".json"
    filepath = os.path.join(RO_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"No sample RO found for id '{ro_id}'")

    try:
        result = run_pipeline(filepath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {str(e)}")

    RUN_RESULTS[result["run_id"]] = result
    return result


@app.get("/ro/runs/{run_id}/insights")
def get_insights(run_id: str):
    """Retrieve a previously computed result by its run_id."""
    result = RUN_RESULTS.get(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"No result found for run_id '{run_id}'")
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)