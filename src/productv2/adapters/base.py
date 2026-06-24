"""Base types for product platform adapters."""

from __future__ import annotations

from typing import Protocol

from productv2.models import CandidateProduct


class ProductAdapter(Protocol):
    platform: str

    def can_handle(self, candidate: CandidateProduct) -> bool:
        """Return whether this adapter can handle the candidate product."""
