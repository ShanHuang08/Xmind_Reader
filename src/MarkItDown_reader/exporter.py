"""Derived outputs live exclusively inside the new artifact store."""
from MarkItDown_reader.contracts import json_text


def export_files(doc: dict, evidence_status: str) -> dict[str, str]:
    def js(value):
        return json_text(value) + "\n"
    files = {}
    operations = []
    index = []
    for op in doc["operations"]:
        item = {**op, "evidence_status": evidence_status, "source_id": doc["source_id"],
                "normalization_id": doc["normalization_id"],
                "section_ids": list(op["section_ids"])}
        operations.append(item)
        if op["review_status"] != "rejected" and op.get("in_scope"):
            index.append({"operation_id": op["operation_id"], "api_name": op["operation_name"],
                          "method": op["http_method"], "endpoint": op["url_or_path"],
                          "discriminator": op["discriminator"], "role": op["role"],
                          "selection_status": op.get("selection_status"),
                          "selection_reason": op.get("selection_reason"),
                          "usage_logic": op.get("usage_logic"),
                          "review_status": op["review_status"], "evidence_status": evidence_status,
                          "section_ids": item["section_ids"]})
    files["operation_index.json"] = js(operations)
    files["endpoint_index.json"] = js(index)
    files["error_codes.json"] = js([{**row, "source_origin": doc["source_origin"],
                                      "evidence_status": evidence_status} for row in doc["error_codes"]])
    return files
