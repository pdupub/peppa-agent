from __future__ import annotations

from peppa.paths import ROOT_DIR


class PromptError(RuntimeError):
    pass


def load_prompt(relative_path: str) -> str:
    prompt_path = ROOT_DIR / "prompts" / relative_path
    if not prompt_path.exists():
        raise PromptError(f"Missing prompt file: {prompt_path}")
    if not prompt_path.is_file():
        raise PromptError(f"Prompt path is not a file: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise PromptError(f"Prompt file is empty: {prompt_path}")
    return content
