from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReactionData:
    emoji: str
    count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MessageData:
    external_id: str
    author: Optional[str]
    author_external_id: Optional[str]
    content: Optional[str]
    content_raw: Optional[str]
    created_at: Optional[str]
    edited_at: Optional[str]
    thread_root_external_id: Optional[str]
    reply_to_external_id: Optional[str]
    reactions: List[ReactionData] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
