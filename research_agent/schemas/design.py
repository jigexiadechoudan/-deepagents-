from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DesignObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str = Field(description="设计对象类型，如 dataObject、Page、Action")
    data: dict[str, Any] = Field(description="设计文档中定义的对象字段")
    evidence: list[str] = Field(
        min_length=1,
        description="支持这个对象的测试材料原文片段",
    )


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objects: list[DesignObject] = Field(description="从材料中提取的设计对象")
    omissions: list[str] = Field(description="尚未完整提取的内容")
    conflicts: list[str] = Field(description="材料中互相矛盾的内容")
    unknowns: list[str] = Field(description="材料没有明确说明的信息")


if __name__ == "__main__":
    result = ExtractionResult(
        objects=[
            DesignObject(
                object_type="dataObject",
                data={
                    "id": "obj_customer_material_ref",
                    "label": "客户料号对照",
                    "physicalName": "t_sal_customer_material_ref",
                },
                evidence=[
                    "客户料号与内部料品的对照，一个客户料号对应一个内部料品"
                ],
            )
        ],
        omissions=[],
        conflicts=[],
        unknowns=[],
    )

    print(result.model_dump_json(indent=2))