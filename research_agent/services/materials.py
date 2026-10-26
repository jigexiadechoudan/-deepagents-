from pathlib import Path
from research_agent.config import MATERIAL_PATH, REFERENCE_PATH
from deepagents.backends.utils import create_file_data

def load_material(material_path: Path = MATERIAL_PATH) -> str:
    return material_path.read_text(encoding="utf-8")


def load_reference(reference_path: Path = REFERENCE_PATH) -> str:
    return reference_path.read_text(encoding="utf-8")

def load_skill_files(skill_dir: Path) -> dict:
    if not (skill_dir / "SKILL.md").is_file():
        raise FileNotFoundError(f"缺少提取技能，不能静默降级：{skill_dir / 'SKILL.md'}")
    files = {}

    for path in skill_dir.rglob("*.md"):
        relative_path = path.relative_to(skill_dir).as_posix()
        virtual_path = f"/skills/{skill_dir.name}/{relative_path}"

        content = path.read_text(encoding="utf-8")
        files[virtual_path] = create_file_data(content)

    return files


def load_skill_references(skill_files: dict) -> dict[str, str]:
    """从本轮 VFS 快照预加载附属 Markdown，避免模型为读同一份文件额外往返。"""
    return {
        path: data["content"]
        for path, data in skill_files.items()
        if "/references/" in path
    }


if __name__ == "__main__":
    material = load_material()
    print("材料字符数：", len(material))
    print("材料前 200 个字符：")
    print(material[:200])
