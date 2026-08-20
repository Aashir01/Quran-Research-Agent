"""Model access: registry, adapters, routing.

Everything about *which* model runs lives here, and nothing else in the codebase
names a model. The rest of the system asks for a role and gets an answer or a
:class:`~qra.ai.router.NoModelAvailable`.
"""

from qra.ai.base import (
    ChatResult,
    EmbeddingResult,
    ProviderRefusal,
    ProviderUnavailable,
    RerankResult,
    TranscriptionResult,
)
from qra.ai.router import NoModelAvailable, Router, candidates, default_router

__all__ = [
    "ChatResult",
    "EmbeddingResult",
    "NoModelAvailable",
    "ProviderRefusal",
    "ProviderUnavailable",
    "RerankResult",
    "Router",
    "TranscriptionResult",
    "candidates",
    "default_router",
]
