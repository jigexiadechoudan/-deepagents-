"""对照本轮设计正文的字段目录；不把示例值当成业务事实或必填性标准。"""

import json
import re
import hashlib
from pathlib import Path

from research_agent.schemas.typed import _DATA_BY_TYPE
from research_agent.schemas.vocabulary import REFERENCE_TABLE_SHA256


def inspect_reference_contract(reference: str, field_table_path: Path | None = None) -> dict:
    headings = list(re.finditer(r"^### (.+)$", reference, re.MULTILINE))
    documented = {}
    unmodeled = set()
    attached = {"constraint", "openItem", "assumption", "quality", "note"}
    for index, heading in enumerate(headings):
        declaration = re.search(r"([A-Za-z][A-Za-z0-9]*)[（(]", heading.group(1))
        if declaration and declaration.group(1) not in _DATA_BY_TYPE:
            unmodeled.add(declaration.group(1))
        kind = next((name for name in _DATA_BY_TYPE
                     if re.search(rf"\b{re.escape(name)}\b", heading.group(1))), None)
        if kind is None:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(reference)
        example = re.search(r"```JSON\s*(.*?)```", reference[heading.end():end], re.DOTALL)
        if not example:
            continue
        sample = json.loads(example.group(1))
        if not isinstance(sample, dict):
            continue
        model = _DATA_BY_TYPE[kind]
        schema_fields = {field.alias or name for name, field in model.model_fields.items()}
        documented[kind] = {
            "reference_line": reference.count("\n", 0, heading.start()) + 1,
            "reference_fields": sorted(sample), "schema_fields": sorted(schema_fields - {"object_type"}),
            "missing_in_schema": sorted(set(sample) - schema_fields),
            "extra_to_review": sorted(schema_fields - set(sample) - attached - {"id", "object_type"}),
        }
    field_table = {"source_sha256": REFERENCE_TABLE_SHA256, "status": "snapshot_only"}
    if field_table_path is not None and field_table_path.is_file():
        actual = hashlib.sha256(field_table_path.read_bytes()).hexdigest()
        field_table.update(actual_sha256=actual, path=str(field_table_path),
                           status="matched" if actual == REFERENCE_TABLE_SHA256 else "changed")
    return {
        "objects": documented,
        "missing_types": sorted(set(_DATA_BY_TYPE) - set(documented)),
        "unmodeled_types": sorted(unmodeled),
        "field_table": field_table,
        "field_mismatches": {kind: item["missing_in_schema"] for kind, item in documented.items()
                             if item["missing_in_schema"]},
        "evidence_scope": "Markdown 示例顶层字段及词表来源附件版本对账；不证明色标必填或全部业务语义已验证",
    }
