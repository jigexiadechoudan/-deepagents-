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
    # auto=优先复用输入版本匹配的人工审核缓存，否则生成待审核清单。
    # file=只读带审核信息和输入指纹的清单包；off=显式跳过覆盖基准。
    baseline_mode: str = "auto"
    baseline_manifest_path: Path | None = None
    skill_dir: Path = PROJECT_DIR / "research_agent" / "skills" / "design-model-extraction"


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
