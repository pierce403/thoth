import os
import pathlib
try:
    import tomllib  # type: ignore
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = pathlib.Path("config/thoth.toml")


@dataclass
class ChannelConfig:
    name: str
    url: str
    enabled: bool = True
    mode: str = "auto"


@dataclass
class SourceConfig:
    name: str
    type: str
    base_url: str
    enabled: bool = True
    selectors: Dict[str, str] = field(default_factory=dict)
    channels: List[ChannelConfig] = field(default_factory=list)


@dataclass
class ThothConfig:
    db_path: str
    profile_dir: str
    headless: bool
    slow_mo_ms: int
    loop_delay_seconds: int
    scrape: Dict[str, Any]
    sources: List[SourceConfig]


def resolve_config_path(cli_path: Optional[str] = None) -> pathlib.Path:
    if cli_path:
        return pathlib.Path(cli_path)
    env_path = os.getenv("THOTH_CONFIG")
    if env_path:
        return pathlib.Path(env_path)
    return DEFAULT_CONFIG_PATH


def _parse_sources(raw_sources: List[Dict[str, Any]]) -> List[SourceConfig]:
    sources: List[SourceConfig] = []
    for raw in raw_sources:
        channels = [
            ChannelConfig(
                name=channel.get("name", ""),
                url=channel.get("url", ""),
                enabled=channel.get("enabled", True),
                mode=channel.get("mode", "auto"),
            )
            for channel in raw.get("channels", [])
        ]
        sources.append(
            SourceConfig(
                name=raw.get("name", ""),
                type=raw.get("type", ""),
                base_url=raw.get("base_url", ""),
                enabled=raw.get("enabled", True),
                selectors=raw.get("selectors", {}),
                channels=channels,
            )
        )
    return sources


def load_config(cli_path: Optional[str] = None) -> ThothConfig:
    path = resolve_config_path(cli_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    thoth = raw.get("thoth", {})
    scrape = raw.get("scrape", {})
    sources = _parse_sources(raw.get("sources", []))

    return ThothConfig(
        db_path=thoth.get("db_path", "data/thoth.db"),
        profile_dir=thoth.get("profile_dir", "data/profiles"),
        headless=bool(thoth.get("headless", False)),
        slow_mo_ms=int(thoth.get("slow_mo_ms", 200)),
        loop_delay_seconds=int(thoth.get("loop_delay_seconds", 20)),
        scrape=scrape,
        sources=sources,
    )
