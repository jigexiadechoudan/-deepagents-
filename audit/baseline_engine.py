# -*- coding: utf-8 -*-
"""场景基准通用核对引擎：清单（材料事实）驱动，覆盖下限语义。

与 audit/baseline_check.py v3 的关系：核对过程逐段迁移自 v3，材料事实数据
外置为 BaselineManifest 清单（research_agent/schemas/baseline.py），由清单
生成器自动产出或人工编写。相对 v3 的三处计划内差异（离线回归
audit/parity_check.py 逐项归因）：
- 关系基数：v3 用 shipment/loadbill/装车 特判，现由清单逐关系声明期望；
- 服务出入参：v3 用 agent 生成的对象 ID 表达（字段没落到主表时可能虚假
  通过），现用物理名表达，引擎解析，解析不了如实 FAIL；
- 字段级断言（必填/默认值/容量）只在字段本体解析到主表后运行：字段缺失
  由 presence 一条 FAIL 负责根因，不再对缺失字段重复报表单层失败。
覆盖下限之外新增两类 v3 没有的必建语义（第二阶段加入）：
- 关系必建：清单 relations 逐条必须在提取结果有承接；缺失但已在
  omissions/unknowns 声明缺口降级为告警，静默缺失=FAIL。
- 非主表对象字段（FieldFact.onObject）：材料在档案等对象上逐字点名的
  字段必须建 Attribute 承接；对象未建或字段缺失同样走声明降级阶梯。
清单里没有的段落自动跳过；内置协议规则（类型白名单、ID 完整性、证据回链、
关系端点非空/不自指）任何材料都跑。覆盖下限：清单枚举的事实缺失 = FAIL，
多出来的对象/字段/动作不罚（合法建模变体交通用校验器与人工复核）。

用法：
    from audit.baseline_engine import run_baseline_engine
    result = run_baseline_engine(extraction_dict, manifest_dict, material_text)
    python -m audit.baseline_engine <extraction.json> <manifest.json> <material.md>
"""
import json
import re
import sys
from collections import Counter

from research_agent.schemas.baseline import BaselineManifest

# 协议内置：对象类型白名单（与 v3 保持同一集合）
KNOWN_TYPES = {
    "Page", "FieldView", "Action", "Option", "Actor", "Relation",
    "Module", "PageGroup", "Application", "Automation",
    "Database", "Project", "Requirement", "Block", "OptionSource",
    "BlockRule", "Feature", "Navigation", "Permission",
    "DataSet", "ExistingSystem", "ExternalDataSource", "Attribute",
    "Artifact", "DataService", "dataObject",
}

REF_TOKEN = re.compile(
    r"^(attr|entity|blk|fv|act|actor|mod|nav|pg|opt|optsrc|rel|rule|db|svc|auto|feat|app|proj|ds)_[a-z0-9_]+$"
)

MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", MD_ESCAPE.sub(r"\1", text or ""))


def iter_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_strings(v)


def all_text(node):
    out = []

    def walk(n):
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return "\n".join(out)


def _keyword_hit(text: str, keyword: str) -> bool:
    """关键词支持 | 分隔的多候选；匹配前去掉全部空白（与 v3 的宽松匹配一致）。"""
    plain = re.sub(r"\s", "", text or "")
    return any(re.sub(r"\s", "", alt) in plain for alt in keyword.split("|"))


def run_baseline_engine(extraction: dict, manifest: dict, material: str) -> dict:
    """可编程入口：清单驱动的覆盖下限核对，返回结构与 v3 一致。"""
    m = BaselineManifest.model_validate(manifest)
    names = m.names
    material_norm = normalize(material)
    objects = extraction.get("objects", [])
    gap_text = " ".join(str(x) for x in
                        extraction.get("omissions", []) + extraction.get("unknowns", []))
    items = []

    def declared_gap(keyword: str) -> bool:
        """事实缺失但已在 omissions/unknowns 里声明缺口（关键词任一命中）。"""
        return any(alt in gap_text for alt in keyword.split("|"))

    def locate_object(name: str):
        """按材料语言定位 dataObject：中文名优先，物理名兜底。"""
        for d in by_type.get("dataObject", []):
            if d.get("label") == name or d.get("physicalName") == name:
                return d.get("id")
        return None

    def check(key, ok, detail="", warn_only=False):
        status = "pass" if ok else ("warn" if warn_only else "fail")
        items.append({"status": status, "check": names.get(key, key), "detail": str(detail)})
        return ok

    by_type = {}
    for o in objects:
        by_type.setdefault(o["object_type"], []).append(o["data"])

    # ---- 内置 1：类型白名单（只查未知类型；数量不做精确断言）----
    unknown = set(by_type) - KNOWN_TYPES
    check("类型:无未知对象类型", not unknown, f"未知 {unknown}")

    # ---- 语义索引：页面按 kind、字段位按所在页面（过程逻辑同 v3）----
    pages = {p.get("kind"): p for p in by_type.get("Page", [])}
    fv_by_page = {}
    blocks = by_type.get("Block", [])
    for fv in by_type.get("FieldView", []):
        blk = next((b for b in blocks if b.get("id") == fv.get("block")), None)
        page_id = blk.get("page") if blk else fv.get("block")
        fv_by_page.setdefault(page_id, []).append(fv)

    def fvs_of(kind):
        pid = pages.get(kind, {}).get("id")
        return fv_by_page.get(pid, [])

    attrs_by_id = {a.get("id"): a for a in by_type.get("Attribute", [])}
    main_do_id = None
    main_attrs = {}
    if m.mainObject and m.mainObject.physicalName:
        main_do_id = next((d.get("id") for d in by_type.get("dataObject", [])
                           if d.get("physicalName") == m.mainObject.physicalName), None)
        main_attrs = {a.get("physicalName"): a for a in by_type.get("Attribute", [])
                      if a.get("dataObject") == main_do_id}

    def form_fv(phys):
        return next((fv for fv in fvs_of("form")
                     if (attrs_by_id.get(fv.get("bind")) or {}).get("physicalName") == phys
                     or fv.get("bind") == phys), None)

    # ---- 清单：页面形态（缺失 FAIL，多建不罚）----
    if m.pages and m.pages.kinds:
        default = f"页面:{len(m.pages.kinds)}种kind齐全"
        check(names.get("pages_kinds", default), set(m.pages.kinds) <= set(pages),
              f"实际 {set(pages)}（缺失按 FAIL，多建不罚）")

    # ---- 清单：主表字段覆盖下限（缺失 FAIL；清单外多出 WARN）----
    main_fields = [f for f in m.fields if not f.onObject]
    onobject_groups: dict = {}
    for f in m.fields:
        if f.onObject:
            onobject_groups.setdefault(f.onObject, []).append(f)

    if m.mainObject and main_fields:
        manifest_names = {f.physicalName for f in main_fields}
        missing_fields = manifest_names - set(main_attrs)
        check(names.get("fields_presence",
                        f"主表字段:清单{len(main_fields)}个物理名全部在场"),
              not missing_fields, f"缺失 {sorted(missing_fields)}")
        extra_fields = set(main_attrs) - manifest_names
        if extra_fields:
            items.append({"status": "warn",
                          "check": names.get("fields_extra", "主表字段:清单外多出"),
                          "detail": f"{sorted(extra_fields)}（人工确认是否合理）"})
        for f in main_fields:
            a = main_attrs.get(f.physicalName)
            if not a:
                continue
            if f.label:
                check(f"字段中文名:{f.physicalName}", a.get("label") == f.label,
                      f"期望 {f.label}，实际 {a.get('label')}", warn_only=True)
            if f.type:
                cap_match = re.match(r"varchar\((\d+)\)", f.type)
                if cap_match:
                    cap = (a.get("capacity") or {}).get("maxLength")
                    check(f"容量:{f.physicalName}", cap == int(cap_match.group(1)),
                          f"期望 {cap_match.group(1)}，实际 {cap}")
                elif f.type == "datetime":
                    check(f"类型:{f.physicalName}", a.get("bizType") == "datetime",
                          f"实际 {a.get('bizType')}")
                elif f.type == "text":
                    cap = a.get("capacity") or {}
                    check(f"类型:{f.physicalName}",
                          a.get("bizType") == "text" and not cap.get("maxLength"),
                          f"bizType={a.get('bizType')}, capacity={cap}")
            if f.formRequired is not None:
                fv = form_fv(f.physicalName)
                check(f"必填:{f.physicalName}", fv is not None and fv.get("required") == f.formRequired,
                      f"期望 {f.formRequired}，实际 {fv and fv.get('required')}")
            if f.formDefault is not None:
                fv = form_fv(f.physicalName)
                check(f"表单默认:{f.label}={f.formDefault}",
                      fv and str(fv.get("defaultValue")) == f.formDefault,
                      f"实际 {fv and fv.get('defaultValue')}")
        expected_primaries = sorted(f.physicalName for f in main_fields if f.primary)
        if expected_primaries:
            primaries = sorted(n for n, a in main_attrs.items() if a.get("primary"))
            check(f"主键:主表仅 {'、'.join(expected_primaries)}",
                  primaries in ([], expected_primaries),
                  f"实际 {primaries}（清单仅声明 {expected_primaries} 为主键）")

    # ---- 清单：非主表对象上的字段（材料逐字点名的档案字段等）----
    for obj_name, group in onobject_groups.items():
        obj_id = locate_object(obj_name)
        attrs_on = {a.get("physicalName"): a for a in by_type.get("Attribute", [])
                    if obj_id and a.get("dataObject") == obj_id}
        missing = sorted({f.physicalName for f in group} - set(attrs_on))
        if missing:
            status = "warn" if declared_gap(obj_name + "|" + "|".join(missing)) else "fail"
            items.append({
                "status": status, "check": f"对象字段:{obj_name}",
                "detail": (f"缺失 {missing}" + ("" if obj_id else "｜对象未建")
                           + ("｜已在 omissions/unknowns 声明缺口" if status == "warn" else "")),
            })
        for f in group:
            a = attrs_on.get(f.physicalName)
            # 只报不一致；在场且一致时保持沉默（与覆盖下限的报告风格一致）
            if a and f.label and a.get("label") != f.label:
                items.append({"status": "warn", "check": f"字段中文名:{f.physicalName}",
                              "detail": f"期望 {f.label}，实际 {a.get('label')}"})

    # ---- 清单：列表页查询默认值 ----
    for qd in m.queryDefaults:
        q_fv = next((fv for fv in fvs_of("list")
                     if (attrs_by_id.get(fv.get("bind")) or {}).get("physicalName") == qd.physicalName
                     and fv.get("defaultValue")), None)
        check(names.get(f"query_default:{qd.physicalName}", f"查询默认:{qd.physicalName}"),
              q_fv and str(q_fv.get("defaultValue")) in qd.value.split("|"),
              f"实际 {q_fv and q_fv.get('defaultValue')}")

    # ---- 清单：详情页全部只读 ----
    if m.detailReadonlyAll:
        check("详情:全部只读", all(fv.get("readonly") is True for fv in fvs_of("detail")),
              f"例外 {[fv.get('label') for fv in fvs_of('detail') if fv.get('readonly') is not True]}")

    # ---- 清单：索引事实（结构位置不限）----
    if m.indexes:
        text_all = all_text(extraction)
        for idx in m.indexes:
            key = f"index:{idx.name or ','.join(idx.columns)}"
            if idx.name:
                check(names.get(key, f"索引:{idx.name}事实在"), idx.name in text_all)
            if idx.columns:
                joined = ", ".join(idx.columns)
                check(names.get(key, f"索引:{','.join(idx.columns)}联合索引事实在"),
                      normalize(f"({joined})") in normalize(text_all) or joined in text_all)
        if not by_type.get("Database"):
            items.append({"status": "warn", "check": "未建Database对象",
                          "detail": "索引以约束语句承载（结构化丢失，事实保留）"})

    # ---- 内置 2：关系端点完整与不自指；清单：关系基数期望 ----
    for r in by_type.get("Relation", []):
        rid = r.get("label") or r.get("id")
        to_obj = (r.get("to") or {}).get("dataObject")
        frm_obj = (r.get("from") or {}).get("dataObject")
        check(f"关系两端:{rid}", bool(to_obj) and bool(frm_obj),
              f"from={frm_obj} to={to_obj}（端点为空）")
        check(f"关系自指:{rid}", to_obj and to_obj != frm_obj, f"{frm_obj} 指向自身")
        if m.relations:
            haystack = " ".join([str(r.get("label") or ""), str(r.get("from") or {}), str(r.get("to") or {})])
            entry = next((e for e in m.relations
                          if any(alt in haystack for alt in e.matchLabel.split("|"))), None)
            if entry:
                check(f"关系方向:{rid}", r.get("cardinality") in entry.cardinality.split("|"),
                      f"实际 {r.get('cardinality')}")

    # ---- 清单：材料枚举的关系必须被承接（缺失但已声明缺口=warn，静默缺失=fail）----
    for e_rel in m.relations:
        present = any(any(alt in " ".join([str(r.get("label") or ""), str(r.get("id") or ""),
                                           str(r.get("from") or {}), str(r.get("to") or {})])
                           for alt in e_rel.matchLabel.split("|"))
                      for r in by_type.get("Relation", []))
        if present:
            continue
        name = f"关系必建:{e_rel.matchLabel}"
        if declared_gap(e_rel.matchLabel):
            items.append({"status": "warn", "check": name,
                          "detail": "材料关联关系表枚举｜缺失但已在 omissions/unknowns 声明缺口"})
        else:
            items.append({"status": "fail", "check": name,
                          "detail": "材料关联关系表枚举｜缺失且未声明缺口"})

    # ---- 清单：选项覆盖下限（清单枚举值必须都在；多出不罚）----
    if m.optionValues and m.optionValues.values:
        opts = by_type.get("Option", [])
        have_values = {str(o.get("value")) for o in opts}
        missing_opts = set(m.optionValues.values) - have_values
        check(names.get("option_values", "选项:清单枚举值全部在场"),
              not missing_opts, f"缺失 {sorted(missing_opts)}")
    if m.optionValues and m.optionValues.referenceFields:
        ref_srcs = [s for s in by_type.get("OptionSource", []) if s.get("kind") == "reference"]
        need = len(m.optionValues.referenceFields)
        check(names.get("ref_sources", f"取值来源:引用源不少于{need}个"),
              len(ref_srcs) >= need, f"实际 {len(ref_srcs)}")
        if m.mainObject:
            # 引用源按字段物理名归组：模型把引用源错绑到其他对象的同名属性上，
            # 重复建模同样能被抓到（v3 的 id 子串启发式的泛化版）。
            phys_to_ids = {}
            for a in by_type.get("Attribute", []):
                pn = a.get("physicalName")
                if pn:
                    phys_to_ids.setdefault(pn, set()).add(a.get("id"))
            for phys in m.optionValues.referenceFields:
                bound = [s for s in ref_srcs
                         if s.get("valueAttribute") in phys_to_ids.get(phys, set())]
                if len(bound) > 1:
                    items.append({"status": "warn",
                                  "check": names.get("ref_sources_dedup", "取值来源:引用源重复"),
                                  "detail": f"{phys}: {len(bound)} 份｜跨页面应共用一份"})

    # ---- 清单：按钮覆盖下限 + 条件/行为事实 ----
    acts = {}
    for a in by_type.get("Action", []):
        lab = a.get("label")
        key = lab[0] if isinstance(lab, list) and lab else lab
        acts.setdefault(key, a)
    life_structured = all_text([o["data"].get("openLogic") for o in objects]
                               + [o["data"].get("saveLogic") for o in objects])
    life_notes = all_text([o["data"].get("note") for o in objects]
                          + [o["data"].get("constraint") for o in objects])
    for b in m.buttons:
        act = acts.get(b.label, {})
        check(f"按钮在场:{b.label}", b.label in acts)
        if b.conditionMustContain:
            cond = act.get("condition") or ""
            check(names.get(f"button:{b.label}:condition", b.name or f"条件:{b.label}=条件关键词"),
                  all(k in cond for k in b.conditionMustContain), f"实际 {cond}")
        if b.conditionMustBeEmpty:
            cond = act.get("condition")
            # "无条件"的常见抄写变体（如整句"显示条件为 无条件"）同样视为无条件
            check(names.get(f"button:{b.label}:condition", b.name or f"条件:{b.label}=无条件"),
                  cond is None or cond == "" or "无条件" in str(cond), f"实际 {cond}")
        if b.paramsContain:
            dparams = [str(p) for p in (act.get("params") or [])]
            check(names.get(f"button:{b.label}:params", f"{b.label}:参数关键词"),
                  all(any(k in p for p in dparams) or k in all_text(act.get("logic"))
                      for k in b.paramsContain))
        if b.targetPageKind:
            check(names.get(f"button:{b.label}:target", f"{b.label}:跳转目标页"),
                  act.get("target") == pages.get(b.targetPageKind, {}).get("id"),
                  f"实际 {act.get('target')}")
        if b.logicContains:
            scope = all_text(act.get("logic")) if b.logicScope == "action" \
                else all_text(act) + life_structured
            check(names.get(f"button:{b.label}:logic", f"{b.label}:逻辑关键词"),
                  all(_keyword_hit(scope, k) for k in b.logicContains))

    # ---- 清单：表单生命周期（结构化优先，note/constraint 降级为告警）----
    for i, lc in enumerate(m.lifecycles):
        keywords = [kw for kw in (lc.trigger, lc.subject, lc.verb) if kw]

        def cond(text, _kws=keywords):
            return all(_keyword_hit(text, kw) for kw in _kws)

        name = names.get(f"lifecycle:{i}", f"表单逻辑:{lc.trigger}|{lc.subject}")
        if cond(life_structured):
            items.append({"status": "pass", "check": name, "detail": ""})
        elif cond(life_notes) or cond(life_structured + life_notes):
            items.append({"status": "warn", "check": name,
                          "detail": "时点仅存于 note/constraint 文本，未结构化到 openLogic/saveLogic"})
        else:
            items.append({"status": "fail", "check": name, "detail": ""})

    # ---- 清单：字段位交互行为 ----
    for fb in m.fieldBehaviors:
        fv = form_fv(fb.physicalName)
        fv_text = all_text(fv) if fv else ""
        check(names.get(f"field_behavior:{fb.physicalName}", f"字段行为:{fb.physicalName}"),
              any(k in fv_text for k in fb.keywords),
              f"关键词 {fb.keywords} 未出现在该字段位文本")

    # ---- 清单：数据服务出入参（物理名解析为属性 ID 再比对）----
    if m.serviceIO:
        svc = by_type.get("DataService", [])
        if svc:
            def resolve(phys_list):
                resolved = {main_attrs[p].get("id") for p in phys_list if p in main_attrs}
                unresolved = [p for p in phys_list if p not in main_attrs]
                return resolved, unresolved

            have_in = set(svc[0].get("inputs") or [])
            have_out = set(svc[0].get("outputs") or [])
            req_in, miss_in = resolve(m.serviceIO.inputs)
            req_out, miss_out = resolve(m.serviceIO.outputs)
            check(names.get("service_inputs", "服务:清单输入参数覆盖"),
                  not miss_in and req_in <= have_in,
                  f"缺失 {sorted(req_in - have_in)}" + (f"｜清单物理名未解析 {miss_in}" if miss_in else ""))
            check(names.get("service_outputs", "服务:清单输出参数覆盖"),
                  not miss_out and req_out <= have_out,
                  f"缺失 {sorted(req_out - have_out)}" + (f"｜清单物理名未解析 {miss_out}" if miss_out else ""))
        else:
            check("服务:存在", False, "DataService 未建")

    # ---- 内置 3：ID 唯一 + 引用无悬空（清单索引名不算对象引用）----
    ids = [o["data"].get("id") for o in objects if o["data"].get("id")]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    check("ID:唯一", not dup, f"重复 {dup}")
    id_set = set(ids)
    non_ref = {idx.name for idx in m.indexes if idx.name}
    broken = []
    for o in objects:
        for s in iter_strings(o["data"]):
            if s in non_ref:
                continue
            if REF_TOKEN.match(s) and s not in id_set:
                broken.append(f"{o['data'].get('id')}->{s}")
    check("引用:无悬空", not broken, f"悬空 {broken[:8]}")

    # ---- 内置 4：证据回链 ----
    ev_fail = []
    for o in objects:
        for ev in o.get("evidence", []):
            if normalize(ev) not in material_norm:
                ev_fail.append((o["data"].get("id") or o["object_type"], ev[:70]))
    check("证据:全部逐字命中原文", not ev_fail, f"{len(ev_fail)} 条未命中")
    for oid, ev in ev_fail:
        items.append({"status": "fail", "check": "证据未命中", "detail": f"{oid}｜{ev}"})

    passed = sum(1 for i in items if i["status"] == "pass")
    warns = sum(1 for i in items if i["status"] == "warn")
    fails = sum(1 for i in items if i["status"] == "fail")
    return {"passed": passed, "warnings": warns, "failures": fails, "items": items}


def main(extraction_path: str, manifest_path: str, material_path: str) -> int:
    with open(extraction_path, encoding="utf-8") as f:
        result = json.load(f)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    with open(material_path, encoding="utf-8") as f:
        material = f.read()
    r = run_baseline_engine(result, manifest, material)
    print(f"通过 {r['passed']} 项，告警 {r['warnings']} 项，失败 {r['failures']} 项")
    for kind, mark in (("warn", " !"), ("fail", " ×")):
        rows = [i for i in r["items"] if i["status"] == kind]
        if rows:
            print(f"\n-- {'告警' if kind == 'warn' else '失败'} --")
            for i in rows:
                print(f" {mark} {i['check']}｜{i['detail']}")
    return 1 if r["failures"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
