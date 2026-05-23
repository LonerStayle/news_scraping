"""Domain config loader — keywords + sources from `domains/<name>/`.

The codebase is designed to be reusable across domains: swap the YAML files
in `domains/<other-topic>/` and the rest of the pipeline works unchanged
(CLAUDE.md §3.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DOMAINS_ROOT = Path(__file__).resolve().parents[2] / "domains"


@dataclass(frozen=True)
class Source:
    domain: str
    name: str


@dataclass(frozen=True)
class DomainConfig:
    keywords: list[str]
    sources: list[Source]


def load_domain(name: str = "ai_news", root: Path | None = None) -> DomainConfig:
    base = (root or DOMAINS_ROOT) / name
    if not base.is_dir():
        raise FileNotFoundError(f"domain config not found: {base}")

    keywords_raw = _load_yaml(base / "keywords.yaml").get("keywords")
    if not isinstance(keywords_raw, list) or not keywords_raw:
        raise ValueError(f"{base / 'keywords.yaml'} must define a non-empty 'keywords' list")

    sources_raw = _load_yaml(base / "sources.yaml").get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ValueError(f"{base / 'sources.yaml'} must define a non-empty 'sources' list")

    sources: list[Source] = []
    for item in sources_raw:
        if not isinstance(item, dict) or "domain" not in item or "name" not in item:
            raise ValueError(f"invalid source entry: {item!r} (expected domain + name)")
        sources.append(Source(domain=str(item["domain"]), name=str(item["name"])))

    return DomainConfig(keywords=[str(k) for k in keywords_raw], sources=sources)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} root must be a YAML mapping, got {type(loaded).__name__}")
    return loaded
