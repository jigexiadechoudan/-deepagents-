"""仅供宿主纠错的内部协议，不改变最终 ExtractionResult。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from research_agent.schemas.typed import DesignObject


class ObjectRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    replacement: DesignObject
    changed_fields: list[str] = Field(
        min_length=1, description="实际改动的顶层字段路径，如 data.readonly、data.note、evidence"
    )
    reason: str = Field(min_length=1, description="错误原因和此次修正的依据，含关联影响")
    evidence: list[str] = Field(min_length=1, description="支持修正的连续原文，逐字复制")


class ReportRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["omissions", "conflicts", "unknowns"]
    previous: str | None = Field(description="要替换或删除的现有条目；新增时为 null")
    revised: str | None = Field(description="修正后的条目；问题已实际解决时可为 null")
    reason: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class ExtractionRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacements: list[ObjectRevision] = Field(default_factory=list)
    additions: list[DesignObject] = Field(default_factory=list, description="仅补材料有据的遗漏对象")
    report_changes: list[ReportRevision] = Field(default_factory=list)
