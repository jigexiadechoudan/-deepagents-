"""绑定输入版本的基准存储：自动生成只存待审核稿，只有人工审核记录可复用。"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from research_agent.config import PROJECT_DIR, Settings
from research_agent.schemas.baseline import BaselineManifest
from research_agent.services.baseline_generator import generate_baseline_manifest, self_check_manifest


def digest(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_fingerprints(settings: Settings, material: str, reference: str, skill_files: dict) -> dict:
    """只使用本轮实际加载的正文快照；规则文件变化也使审核缓存失效。"""
    rule_paths = [
        "research_agent/schemas/baseline.py", "research_agent/services/checks.py",
        "research_agent/services/baseline_generator.py", "audit/baseline_engine.py",
        "research_agent/agent/prompts.py", "research_agent/services/repair.py",
        "research_agent/schemas/repair.py", "research_agent/services/baseline_store.py",
        "research_agent/schemas/vocabulary.py",
        "research_agent/services/fact_review.py",
        "research_agent/agent/middleware.py",
        "research_agent/agent/model.py", "research_agent/agent/factory.py",
    ]
    field_table = settings.reference_path.parent / "图片和附件" / "设计模型-字段总表.xlsx"
    return {
        "material": digest(material), "reference": digest(reference),
        "schema": digest((PROJECT_DIR / "research_agent/schemas/typed.py").read_text(encoding="utf-8")),
        "field_table": hashlib.sha256(field_table.read_bytes()).hexdigest() if field_table.is_file() else None,
        "skills": digest({path: data["content"] for path, data in sorted(skill_files.items())}),
        "rules": digest({path: (PROJECT_DIR / path).read_text(encoding="utf-8") for path in rule_paths}),
    }


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_reviewed(path: Path, fingerprints: dict) -> tuple[dict, dict]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if envelope.get("fingerprints") != fingerprints:
        raise ValueError("材料、设计定义、技能或核对规则已变化，基准审核记录失效")
    manifest = BaselineManifest.model_validate(envelope.get("manifest")).model_dump()
    current_sha = digest(manifest)
    if envelope.get("review_status") != "reviewed" or not envelope.get("reviewed_by") \
            or not envelope.get("reviewed_at"):
        raise ValueError("基准尚无人工作出审核记录")
    if envelope.get("manifest_sha256") != current_sha \
            or envelope.get("reviewed_manifest_sha256") != current_sha:
        raise ValueError("基准正文在审核后发生变化，需要重新审核")
    meta = {
        "source": "reviewed_file", "path": str(path), "fingerprints": fingerprints,
        "review_status": "reviewed", "reviewed_by": envelope["reviewed_by"],
        "reviewed_at": envelope["reviewed_at"], "manifest_sha256": current_sha,
    }
    return manifest, meta


def load_baseline(settings: Settings, material: str, reference: str, skill_files: dict) -> tuple[dict | None, dict]:
    started = perf_counter()
    fingerprints = input_fingerprints(settings, material, reference, skill_files)
    meta = {"source": settings.baseline_mode, "fingerprints": fingerprints}
    try:
        if settings.baseline_mode == "off":
            return None, meta
        if settings.baseline_mode == "file":
            if not settings.baseline_manifest_path:
                raise ValueError("file 模式需要 baseline_manifest_path")
            manifest, loaded = _read_reviewed(Path(settings.baseline_manifest_path), fingerprints)
            meta.update(loaded)
            print("[基准] 已载入与当前输入匹配的人工审核清单", flush=True)
            return manifest, meta
        if settings.baseline_mode != "auto":
            raise ValueError(f"未知 baseline_mode：{settings.baseline_mode}")
        cache_path = settings.output_dir / "baseline_cache" / f"{digest(fingerprints)}.json"
        if cache_path.exists():
            try:
                manifest, loaded = _read_reviewed(cache_path, fingerprints)
            except (ValueError, TypeError, OSError) as error:
                meta["cache_miss_reason"] = str(error)
            else:
                meta.update(loaded, source="reviewed_cache")
                print("[基准] 复用本轮输入对应的人工审核清单", flush=True)
                return manifest, meta
        print("[基准] 没有匹配的审核缓存，从完整材料生成待审核清单……", flush=True)
        generated = generate_baseline_manifest(material, settings)
        meta.update(generated.meta, fingerprints=fingerprints, review_status="pending")
        envelope = {
            "fingerprints": fingerprints, "manifest": generated.manifest,
            "manifest_sha256": digest(generated.manifest), "review_status": "pending",
            "reviewed_manifest_sha256": None, "reviewed_by": None, "reviewed_at": None,
            "generation": generated.meta,
        }
        # 不覆盖尚在人工编辑的清单；每次新生成稿独立留存。
        if cache_path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cache_path = cache_path.with_name(f"{cache_path.stem}_{stamp}.json")
        _write(cache_path, envelope)
        meta["path"] = str(cache_path)
        for warning in generated.meta["self_check"]["warnings"]:
            print(f"[基准] 自检告警：{warning}", flush=True)
        return generated.manifest, meta
    except Exception as error:
        meta.update(source="error", error=str(error))
        print(f"[基准] 本轮未完成基准获取：{error}", flush=True)
        return None, meta
    finally:
        meta["elapsed_seconds"] = round(perf_counter() - started, 3)


def record_baseline_review(source: Path, settings: Settings, reviewer: str) -> Path:
    """仅记录操作者已完成的人工审核；不自动签发业务完整性结论。"""
    from research_agent.services.materials import load_material, load_reference, load_skill_files

    if not reviewer.strip():
        raise ValueError("reviewer 不能为空")
    material, reference = load_material(settings.material_path), load_reference(settings.reference_path)
    fingerprints = input_fingerprints(settings, material, reference, load_skill_files(settings.skill_dir))
    content = json.loads(source.read_text(encoding="utf-8"))
    if "manifest" in content and content.get("fingerprints") != fingerprints:
        raise ValueError("输入版本已经变化，请先按当前材料重新核对清单")
    manifest = BaselineManifest.model_validate(content.get("manifest", content))
    _, report = self_check_manifest(manifest, material)
    if report["dropped"] or any("无证据" in item for item in report["warnings"]):
        raise ValueError("清单有缺失或未命中原文的证据，请补齐后再记录审核")
    manifest_data = manifest.model_dump()
    sha = digest(manifest_data)
    destination = settings.output_dir / "baseline_cache" / f"{digest(fingerprints)}.json"
    _write(destination, {
        "fingerprints": fingerprints, "manifest": manifest_data, "manifest_sha256": sha,
        "review_status": "reviewed", "reviewed_manifest_sha256": sha,
        "reviewed_by": reviewer.strip(), "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source), "self_check": report,
    })
    return destination
