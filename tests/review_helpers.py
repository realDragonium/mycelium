from mycelium.draft_review_store import Correction


def correction(action: str, **fields: object) -> Correction:
    """A reviewer correction with every field it does not set left null."""
    blank: dict[str, object] = {
        "operation_ref": None,
        "statement": None,
        "text": None,
        "kind": None,
        "description": None,
        "link": None,
        "tool_name": None,
        "payload_json": None,
        "reason": "The reviewer's reason.",
    }
    return Correction.model_validate({"action": action, **blank, **fields})
