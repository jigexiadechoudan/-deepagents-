# -*- coding: utf-8 -*-
"""按语义键对比两份提取结果：跨运行漂移的回归门禁（v3，配对不看 ID）。

用法：
    python semantic_diff.py <旧.json> <新.json>

输出三类差异：
- 仅旧有：新一轮广度收窄（对象整类消失会在这里出现）
- 仅新有：广度扩张或新增对象
- 两边都有但字段有差异：落点漂移（note/evidence 等天然不稳定的键不参与对比）
"""
import json
import sys
from pathlib import Path

# 参与内容对比时忽略的键：天然随运行漂移或不承载事实
IGNORED_KEYS = {"note", "evidence", "realization", "order"}


def semantic_key(obj, attrs_by_id, blocks_by_id):
    """对象的语义键：尽量用材料锚点（物理名/label/枚举值），不用技术 ID。"""
    d = obj.get("data", {})
    t = obj.get("object_type")

    def label_of(x):
        lab = x.get("label")
        if isinstance(lab, list):
            return lab[0] if lab else None
        return lab

    if t == "Attribute":
        anchor = d.get("physicalName") or label_of(d) or d.get("id")
        owner = d.get("dataObject")
        return (t, owner, anchor)
    if t == "FieldView":
        bind = d.get("bind")
        phys = (attrs_by_id.get(bind) or {}).get("physicalName") or bind
        blk = blocks_by_id.get(d.get("block"))
        page_kind = blk.get("page") if blk else None
        return (t, page_kind, phys)
    if t == "Action":
        return (t, label_of(d) or d.get("id"))
    if t == "Option":
        return (t, str(d.get("value")))
    if t == "OptionSource":
        return (t, d.get("kind"), d.get("valueAttribute") or d.get("id"))
    if t == "Relation":
        frm = (d.get("from") or {}).get("dataObject")
        to = (d.get("to") or {}).get("dataObject")
        return (t, frm, to)
    if t in ("Page", "Block"):
        return (t, d.get("page"), label_of(d) or d.get("kind"))
    anchor = d.get("physicalName") or d.get("name") or label_of(d) or d.get("id")
    return (t, anchor)


def brief(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text[:80] + ("…" if len(text) > 80 else "")


def diff(old: dict, new: dict) -> dict:
    def index(side):
        return (
            {o["data"].get("id"): o["data"] for o in side.get("objects", []) if o["object_type"] == "Attribute"},
            {o["data"].get("id"): o["data"] for o in side.get("objects", []) if o["object_type"] == "Block"},
        )

    attrs_old, blocks_old = index(old)
    attrs_new, blocks_new = index(new)

    old_map, new_map = {}, {}
    for side, target, ab, blk in ((old, old_map, attrs_old, blocks_old),
                                  (new, new_map, attrs_new, blocks_new)):
        for o in side.get("objects", []):
            key = semantic_key(o, ab, blk)
            target.setdefault(key, []).append(o)

    only_old = [k for k in old_map if k not in new_map]
    only_new = [k for k in new_map if k not in old_map]
    changed = []
    for k in old_map:
        if k not in new_map:
            continue
        a = old_map[k][0]["data"]
        b = new_map[k][0]["data"]
        diffs = {}
        for key in set(a) | set(b):
            if key in IGNORED_KEYS or a.get(key) != b.get(key):
                diffs[key] = (brief(a.get(key)), brief(b.get(key)))
        if diffs:
            changed.append((k, diffs))
    return {
        "only_old": sorted(str(k) for k in only_old),
        "only_new": sorted(str(k) for k in only_new),
        "changed": [(str(k), d) for k, d in changed],
    }


def main(old_path: str, new_path: str) -> int:
    old = json.loads(Path(old_path).read_text(encoding="utf-8"))
    new = json.loads(Path(new_path).read_text(encoding="utf-8"))
    r = diff(old, new)
    print(f"仅旧有 {len(r['only_old'])} 项（新一轮广度收窄）：")
    for k in r["only_old"]:
        print("  -", k)
    print(f"仅新有 {len(r['only_new'])} 项（扩张/新增）：")
    for k in r["only_new"]:
        print("  +", k)
    print(f"同对象字段差异 {len(r['changed'])} 项（落点漂移）：")
    for k, diffs in r["changed"]:
        for key, (a, b) in list(diffs.items())[:3]:
            print(f"  ~ {k} · {key}: {a}  =>  {b}")
        if len(diffs) > 3:
            print(f"    …共 {len(diffs)} 个键")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
