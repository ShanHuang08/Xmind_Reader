"""External extraction import and explicit, hash-bound review decisions."""
from copy import deepcopy
from .contracts import FACTS, SCHEMA, digest, document_status, require, validate_document

REVIEW_FIELDS = (*FACTS, "parameters", "examples")


def package(doc: dict) -> dict:
    return {"schema_version": SCHEMA, "source_id": doc["source_id"],
            "conversion_id": doc["conversion_id"], "converted_sha256": doc["converted_sha256"],
            "instructions": "Edit document.operations/error_codes and retain field evidence. Do not invent missing facts. Coverage is reviewed separately.",
            "document": deepcopy(doc)}


def import_extraction(result: dict, base: dict) -> dict:
    require(isinstance(result, dict), "Extraction must be an object")
    for key in ("schema_version", "source_id", "conversion_id", "converted_sha256"):
        require(result.get(key) == base[key], f"Extraction {key} mismatch")
    doc = deepcopy(result.get("document"))
    require(isinstance(doc, dict), "Extraction document required")
    for key in ("schema_version", "vendor", "source_id", "source_origin", "conversion_id", "converted_sha256", "source_markdown"):
        require(doc.get(key) == base[key], f"Cannot change source field {key}")
    require(doc.get("coverage") == base["coverage"], "Review coverage using a decisions file")
    for row in doc.get("operations", []) + doc.get("error_codes", []):
        row["review_status"] = "pending"
    doc["normalization_id"] = ""
    doc["strategy"] = {"id": "imported", "version": "1"}
    doc["status"] = document_status(doc)
    validate_document(doc, base["source_markdown"])
    return {"candidate_hash": digest(doc), "document": doc}


def decision_template(candidate: dict) -> dict:
    doc = candidate["document"]
    return {"candidate_hash": candidate["candidate_hash"],
            "operations": {op["operation_id"]: {key: "pending" for key in REVIEW_FIELDS if op.get(key) is not None}
                           for op in doc["operations"]},
            "error_codes": {str(i): "pending" for i in range(len(doc["error_codes"]))},
            "coverage": {b["block_id"]: {"state": "pending", "reason": "Review required"} for b in doc["coverage"]}}


def apply_decisions(candidate: dict, decisions: dict, base: dict) -> dict:
    require(isinstance(candidate, dict) and isinstance(decisions, dict), "Invalid review files")
    doc = deepcopy(candidate.get("document"))
    require(isinstance(doc, dict), "Candidate document required")
    require(candidate.get("candidate_hash") == digest(doc), "Candidate hash mismatch")
    require(decisions.get("candidate_hash") == candidate["candidate_hash"], "Stale review decisions")
    for key in ("schema_version", "vendor", "source_id", "source_origin", "conversion_id", "converted_sha256", "source_markdown"):
        require(doc.get(key) == base[key], f"Candidate {key} mismatch")
    validate_document(doc, base["source_markdown"])
    template = decision_template(candidate)
    for key in ("operations", "error_codes", "coverage"):
        require(isinstance(decisions.get(key), dict) and set(decisions[key]) == set(template[key]), f"Review must account for all {key}")
    for op in doc["operations"]:
        values = decisions["operations"][op["operation_id"]]
        require(isinstance(values, dict) and set(values) == set(template["operations"][op["operation_id"]]), "Review all populated operation fields")
        require(all(v in {"accept", "reject", "pending"} for v in values.values()), "Invalid review action")
        op["review_status"] = "rejected" if "reject" in values.values() else (
            "pending" if "pending" in values.values() else "accepted")
    for i, row in enumerate(doc["error_codes"]):
        action = decisions["error_codes"][str(i)]
        require(action in {"accept", "reject", "pending"}, "Invalid error review")
        row["review_status"] = {"accept": "accepted", "reject": "rejected", "pending": "pending"}[action]
    for block in doc["coverage"]:
        update = decisions["coverage"][block["block_id"]]
        require(isinstance(update, dict) and set(update) == {"state", "reason"}, "Invalid coverage decision")
        block.update(update)
    doc["status"] = document_status(doc)
    validate_document(doc, base["source_markdown"])
    return doc
