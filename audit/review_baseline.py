"""人工逐项核对清单后，显式记录审核；本命令不代替人工核对，也不调用模型。"""

import argparse
from pathlib import Path

from research_agent.config import Settings
from research_agent.services.baseline_store import record_baseline_review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="已人工核对的基准正文或待审核清单路径")
    parser.add_argument("--reviewer", required=True, help="本次审核人")
    parser.add_argument("--material", type=Path, help="本轮材料路径，默认使用项目测试场景")
    parser.add_argument("--reference", type=Path, help="本轮设计定义路径")
    parser.add_argument("--skill-dir", type=Path, help="本轮技能目录")
    parser.add_argument("--output-dir", type=Path, help="主流程 outputs 目录")
    args = parser.parse_args()
    settings = Settings(model_params={})
    for name in ("material", "reference", "skill_dir", "output_dir"):
        value = getattr(args, name)
        if value is not None:
            setattr(settings, {"material": "material_path", "reference": "reference_path"}.get(name, name), value)
    path = record_baseline_review(args.source, settings, args.reviewer)
    print(f"已记录人工审核并绑定本轮输入：{path}")


if __name__ == "__main__":
    main()
