"""项目路径、环境加载及模型参数；导入模块不会加载 .env。"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent.parent
MATERIAL_PATH = PROJECT_DIR / "测试场景" / "八达光电_客户料号映射_smardaten配置方案.md"
REFERENCE_PATH = PROJECT_DIR.parent / "基础资料" / "设计模型" / "设计模型.md"


@dataclass
class Settings:
    model_params: dict[str, Any]
    material_path: Path = MATERIAL_PATH
    reference_path: Path = REFERENCE_PATH
    output_dir: Path = PROJECT_DIR / "outputs"
    recursion_limit: int = 48
    max_structured_repair_rounds: int = 2
    max_check_rounds: int = 2
    # 场景基准：off=不核对；auto=每次由前置分析步从材料生成清单；file=读审核过的清单文件。
    # auto 已端到端验证（值/标签粒度缺陷已修）；生成清单的全量人工核对通过后即为长期模式。
    baseline_mode: str = "auto"
    baseline_manifest_path: Path | None = (
        PROJECT_DIR / "baselines" / "八达光电_客户料号映射_smardaten配置方案.json"
    )
    skill_dir: Path = Path("F:/调研skill/design-model-extraction")


def load_settings() -> Settings:
    load_dotenv(PROJECT_DIR / ".env")
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise ValueError("请先在 .env 中填写 DEEPSEEK_API_KEY")

    return Settings(
        model_params={
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            "base_url": "https://api.deepseek.com",
            "timeout": 180,
            "max_retries": 1,
            "max_tokens": 65536,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    )
