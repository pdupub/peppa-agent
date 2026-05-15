from __future__ import annotations

from pathlib import Path

from peppa.paths import ROOT_DIR


class PromptError(RuntimeError):
    pass


def load_prompt(relative_path: str) -> str:
    prompt_path = ROOT_DIR / "prompts" / relative_path
    return _load_text_file(prompt_path, "prompt")


def load_skill(relative_path: str) -> str:
    skill_path = ROOT_DIR / "skills" / relative_path
    return _strip_frontmatter(_load_text_file(skill_path, "skill"))


def _load_text_file(path: Path, label: str) -> str:
    if not path.exists():
        raise PromptError(f"Missing {label} file: {path}")
    if not path.is_file():
        raise PromptError(f"{label.title()} path is not a file: {path}")

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise PromptError(f"{label.title()} file is empty: {path}")
    return content


def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---\n"):
        return content

    _, _, remainder = content.partition("\n---\n")
    return remainder.strip() or content
