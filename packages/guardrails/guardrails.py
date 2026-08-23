import re

# --- PII Scrubbing ---

VIN_PATTERN = re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b')
SSN_PATTERN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
PHONE_PATTERN = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')


def scrub_pii(text: str) -> str:
    """
    Masks known PII patterns in a string before it's sent to an LLM
    or written to logs. Returns the scrubbed text.
    """
    if not text:
        return text
    text = VIN_PATTERN.sub('[REDACTED_VIN]', text)
    text = SSN_PATTERN.sub('[REDACTED_SSN]', text)
    text = EMAIL_PATTERN.sub('[REDACTED_EMAIL]', text)
    text = PHONE_PATTERN.sub('[REDACTED_PHONE]', text)
    return text


def scrub_ro_for_llm(ro: dict) -> dict:
    """
    Returns a copy of the RO dict with customer name and VIN removed
    entirely before any data is sent to the LLM. The agent doesn't
    need PII to classify damage or compute uplift — only technical
    and financial fields are relevant to its task.
    """
    import copy
    safe_ro = copy.deepcopy(ro)

    if "customer" in safe_ro:
        safe_ro["customer"].pop("customer_id", None)

    if "vehicle" in safe_ro and "vin" in safe_ro["vehicle"]:
        safe_ro["vehicle"]["vin"] = "[REDACTED_VIN]"

    if "dealer_name" in safe_ro:
        pass  # dealer name is business info, not personal PII - kept

    return safe_ro


# --- Agent Action Allow-list ---

ALLOWED_ACTIONS = {
    "READ_RO",
    "CLASSIFY_DAMAGE",
    "COMPUTE_UPLIFT",
    "RETRIEVE_WARRANTY_RULES",
    "LOG_EVENT",
}


class UnauthorizedActionError(Exception):
    pass


def enforce_action_allowed(action: str):
    """
    Guardrail: raises if the orchestrator attempts an action outside
    its permitted scope. This agent is read-only and analysis-only —
    it must never write to external systems, submit claims, or modify
    the source RO data. Any expansion of the agent's capabilities
    requires explicitly adding to ALLOWED_ACTIONS.
    """
    if action not in ALLOWED_ACTIONS:
        raise UnauthorizedActionError(
            f"Action '{action}' is not in the allowed action list. "
            f"Allowed actions: {sorted(ALLOWED_ACTIONS)}"
        )


if __name__ == "__main__":
    # Quick manual test
    sample_text = "VIN 1FMCU9BZ1MUA10001, contact john.doe@example.com or 555-123-4567"
    print("Before:", sample_text)
    print("After: ", scrub_pii(sample_text))

    try:
        enforce_action_allowed("SUBMIT_CLAIM")
    except UnauthorizedActionError as e:
        print("\nBlocked as expected:", e)

    enforce_action_allowed("CLASSIFY_DAMAGE")
    print("\nAllowed action passed through correctly.")