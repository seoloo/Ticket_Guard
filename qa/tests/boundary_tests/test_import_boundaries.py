"""경계 검사 · 시스템 코드 import 금지 · 정답표가 시스템 쪽으로 새지 않게 · AGENTS.md 2장"""
import ast
from pathlib import Path

from ticket_guard_qa.settings import QA_ROOT_DIR

QA_CODE_DIRS = ("src", "traffic_generators", "fake_targets")
SYSTEM_TOP_LEVEL_MODULES = {"django", "config", "web"}  # 시스템 Django 프로젝트 · 앱 이름
ANSWER_KEY_MODULE = "ticket_guard_qa.answer_key"
MODULES_THAT_MUST_NOT_SEE_ANSWER_KEY = ("system_targets", "traffic_generators", "fake_targets")


def iter_imported_modules(python_file: Path) -> list[str]:
    tree = ast.parse(python_file.read_text(encoding="utf-8"))
    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_modules.append(node.module)
    return imported_modules


def iter_qa_python_files(*folder_names: str) -> list[Path]:
    return [path for folder_name in folder_names for path in (QA_ROOT_DIR / folder_name).rglob("*.py")]


def test_qa_code_never_imports_system_code():
    violations = [
        f"{path.relative_to(QA_ROOT_DIR)}: {module}"
        for path in iter_qa_python_files(*QA_CODE_DIRS)
        for module in iter_imported_modules(path)
        if module.split(".")[0] in SYSTEM_TOP_LEVEL_MODULES
    ]
    assert violations == []


def test_answer_key_stays_out_of_system_side_code():
    target_files = iter_qa_python_files("traffic_generators", "fake_targets") + list(
        (QA_ROOT_DIR / "src" / "ticket_guard_qa" / "system_targets").rglob("*.py")
    )
    violations = [
        f"{path.relative_to(QA_ROOT_DIR)}: {module}"
        for path in target_files
        for module in iter_imported_modules(path)
        if module.startswith(ANSWER_KEY_MODULE)
    ]
    assert violations == []
