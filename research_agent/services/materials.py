from pathlib import Path
from research_agent.config import MATERIAL_PATH, REFERENCE_PATH
from deepagents.backends.utils import create_file_data

def load_material(material_path: Path = MATERIAL_PATH) -> str:
    return material_path.read_text(encoding="utf-8")


def load_reference(reference_path: Path = REFERENCE_PATH) -> str:
    return reference_path.read_text(encoding="utf-8")

def load_skill_files(skill_dir: Path) -> dict:
    files = {}

    for path in skill_dir.rglob("*.md"):
        relative_path = path.relative_to(skill_dir).as_posix()
        virtual_path = f"/skills/{skill_dir.name}/{relative_path}"

        content = path.read_text(encoding="utf-8")
        files[virtual_path] = create_file_data(content)

    return files


if __name__ == "__main__":
    material = load_material()
    print("材料字符数：", len(material))
    print("材料前 200 个字符：")
    print(material[:200])
