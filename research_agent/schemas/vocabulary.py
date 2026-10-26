"""字段总表 v1.6 的明确词表；当前 Markdown 决定成员名，旧产物别名仅兼容读取。"""

from typing import Literal


BusinessType = Literal[
    "text", "longText", "integer", "number", "amount", "percent", "date", "dateTime",
    "boolean", "choice", "reference", "file", "image", "location", "signature", "process", "computed",
    "person", "datetime",  # 历史提取产物使用的别名，不从示例反推新的业务事实。
]
ControlType = Literal[
    "text", "longText", "richText", "number", "amount", "percent", "rating", "switch",
    "date", "dateTime", "choice", "multiChoice", "treeChoice", "cascadeChoice", "reference",
    "person", "organization", "phone", "email", "url", "file", "image", "location", "map",
    "richDoc", "signature", "autoCode", "computed", "display", "custom",
]
VisibilityType = Literal["always", "conditional", "hidden"]
RealizationType = Literal["structured", "partial", "intent"]

# 来源附件的不可变快照指纹；文件变化时先对账，再更新词表。
REFERENCE_TABLE_SHA256 = 'edb2739f8388ba087245749a69870e6866326c4cdf057d32e8aa57327804c67f'
