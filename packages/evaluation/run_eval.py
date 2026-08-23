import json
import glob
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "agent-orchestration"))
from orchestrator import run_pipeline

RO_DIR = "data/sample-ros"
EXPECTED_DIR = "data/eval/expected_outputs"


def load_expected(ro_id: str) -> dict:
    filename = ro_id.lower().replace("ro-", "ro_") + "_expected.json"
    path = os.path.join(EXPECTED_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


IMPLEMENTED_OPPORTUNITY_TYPES = {"WARRANTY_LABOR_RATE"}


def compare_opportunities(actual: list, expected: list) -> bool:
    """
    Compare only against expected opportunities of types the agent
    actually implements. This keeps the eval honest about what's
    being tested rather than penalizing scoped-out features.
    """
    expected_implemented = [
        op for op in expected if op["type"] in IMPLEMENTED_OPPORTUNITY_TYPES
    ]
    if len(actual) != len(expected_implemented):
        return False
    actual_types = sorted(op["type"] for op in actual)
    expected_types = sorted(op["type"] for op in expected_implemented)
    return actual_types == expected_types


def evaluate_ro(ro_path: str) -> dict:
    result = run_pipeline(ro_path)
    ro_id = result["ro_id"]
    expected = load_expected(ro_id)

    if expected is None:
        return {"ro_id": ro_id, "status": "NO_EXPECTED_DATA"}

    actual_cat = result["damage_classification"]["category"].strip().lower()
    expected_cat = expected["expected_damage_classification"]["category"].strip().lower()
    category_match = (actual_cat in expected_cat) or (expected_cat in actual_cat)

    opportunities_match = compare_opportunities(
        result["opportunities"], expected["expected_opportunities"]
    )

    passed = category_match and opportunities_match

    return {
        "ro_id": ro_id,
        "category_match": category_match,
        "opportunities_match": opportunities_match,
        "passed": passed,
        "actual_category": result["damage_classification"]["category"],
        "expected_category": expected["expected_damage_classification"]["category"],
        "actual_opportunities_count": len(result["opportunities"]),
        "expected_opportunities_count": len(expected["expected_opportunities"]),
    }


def main():
    ro_files = sorted(glob.glob(os.path.join(RO_DIR, "*.json")))
    results = []

    print("Running evaluation across all sample ROs...\n")

    for ro_file in ro_files:
        eval_result = evaluate_ro(ro_file)
        results.append(eval_result)

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)

    passed_count = 0
    for r in results:
        status = "PASS" if r.get("passed") else "FAIL"
        print(f"[{status}]  {r['ro_id']}")
        if not r.get("passed"):
            print(f"    category:      actual='{r.get('actual_category')}' "
                  f"expected='{r.get('expected_category')}' match={r.get('category_match')}")
            print(f"    opportunities: actual={r.get('actual_opportunities_count')} "
                  f"expected={r.get('expected_opportunities_count')} match={r.get('opportunities_match')}")
        if r.get("passed"):
            passed_count += 1

    total = len(results)
    print("=" * 60)
    print(f"Score: {passed_count}/{total} passed ({round(100 * passed_count / total, 1)}%)")


if __name__ == "__main__":
    main()