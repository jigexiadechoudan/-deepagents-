"""提取结果结构：外壳协议 + 逐类型强类型数据载荷（定义见 typed.py）。"""

from research_agent.schemas.typed import DesignObject, ExtractionResult

__all__ = ["DesignObject", "ExtractionResult"]


if __name__ == "__main__":
    result = ExtractionResult(
        objects=[
            DesignObject(
                object_type="dataObject",
                data={
                    "object_type": "dataObject",
                    "id": "entity_customer_material_ref",
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

    print(result.model_dump_json(indent=2, by_alias=True))
