from .base import Adapter
from .chatgpt import ChatGPTAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "chatgpt": ChatGPTAdapter,
}

__all__ = ["Adapter", "ChatGPTAdapter", "ADAPTERS"]
