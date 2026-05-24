from __future__ import annotations

from copy import deepcopy
from typing import Any
import json


def normalize_memory_graph_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(arguments)
    collected = {"tags": [], "nodes": [], "edges": []}
    _collect_memory_graph_lists(normalized, collected)

    if not any(collected.values()):
        return normalized

    memory_graph = normalized.get("memory_graph")
    if not isinstance(memory_graph, dict):
        memory_graph = {}
        normalized["memory_graph"] = memory_graph

    for key, items in collected.items():
        if not items:
            continue
        existing_items = _as_list(memory_graph.get(key))
        memory_graph[key] = _unique_records([*existing_items, *items])

    return normalized


def _collect_memory_graph_lists(value: Any, collected: dict[str, list[dict[str, Any]]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in collected:
                collected[key].extend(_graph_items(key, item))
            _collect_memory_graph_lists(item, collected)
        return

    if isinstance(value, list):
        for item in value:
            _collect_memory_graph_lists(item, collected)


def _graph_items(key: str, value: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in _as_list(value)
        if isinstance(item, dict) and _is_memory_graph_item(key, item)
    ]


def _is_memory_graph_item(key: str, item: dict[str, Any]) -> bool:
    if key == "tags":
        return bool(_clean_text(item.get("name")))
    if key == "nodes":
        return bool(
            _clean_text(item.get("ref"))
            and _clean_text(item.get("type"))
            and _clean_text(item.get("title"))
        )
    if key == "edges":
        return bool(
            _clean_text(item.get("source_ref"))
            and _clean_text(item.get("target_ref"))
            and _clean_text(item.get("relation_type"))
        )
    return False


def _unique_records(items: list[Any]) -> list[dict[str, Any]]:
    seen = set()
    unique_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        unique_items.append(item)
    return unique_items


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
