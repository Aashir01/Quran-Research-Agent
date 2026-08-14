"""Shared result types and corpus filters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import Select

from qra.citations import Citation
from qra.models import Ayah


@dataclass
class Span:
    """A retrieved piece of text with everything needed to cite and render it.

    ``text`` is always a verbatim copy of what is in the database. Agents may
    reason about a span but must never re-type its text — see
    :mod:`qra.agents.render`.
    """

    kind: str
    text: str
    citation: Citation
    ayah_id: int | None = None
    ref: str | None = None
    score: float | None = None
    retrieval_mode: str = "deterministic"
    highlights: list[int] = field(default_factory=list)  # word positions, 1-based
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["citation"] = self.citation.to_dict()
        return data


@dataclass
class CorpusFilter:
    """Structural restrictions available to every retrieval mode."""

    surahs: list[int] | None = None
    exclude_surahs: list[int] | None = None
    revelation_place: str | None = None  # makki | madani
    revelation_order_min: int | None = None
    revelation_order_max: int | None = None
    juz: list[int] | None = None
    ruku: list[int] | None = None
    ayah_id_min: int | None = None
    ayah_id_max: int | None = None
    min_word_count: int | None = None
    max_word_count: int | None = None

    def apply(self, stmt: Select, ayah_cls=Ayah) -> Select:
        if self.surahs:
            stmt = stmt.where(ayah_cls.surah_id.in_(self.surahs))
        if self.exclude_surahs:
            stmt = stmt.where(ayah_cls.surah_id.notin_(self.exclude_surahs))
        if self.revelation_place:
            stmt = stmt.where(ayah_cls.revelation_place == self.revelation_place)
        if self.revelation_order_min is not None:
            stmt = stmt.where(ayah_cls.revelation_order >= self.revelation_order_min)
        if self.revelation_order_max is not None:
            stmt = stmt.where(ayah_cls.revelation_order <= self.revelation_order_max)
        if self.juz:
            stmt = stmt.where(ayah_cls.juz.in_(self.juz))
        if self.ruku:
            stmt = stmt.where(ayah_cls.ruku.in_(self.ruku))
        if self.ayah_id_min is not None:
            stmt = stmt.where(ayah_cls.id >= self.ayah_id_min)
        if self.ayah_id_max is not None:
            stmt = stmt.where(ayah_cls.id <= self.ayah_id_max)
        if self.min_word_count is not None:
            stmt = stmt.where(ayah_cls.word_count >= self.min_word_count)
        if self.max_word_count is not None:
            stmt = stmt.where(ayah_cls.word_count <= self.max_word_count)
        return stmt

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in self.__dataclass_fields__)

    def describe(self) -> str:
        bits = []
        if self.revelation_place:
            bits.append(f"{self.revelation_place} surahs")
        if self.surahs:
            bits.append("surahs " + ",".join(map(str, self.surahs)))
        if self.juz:
            bits.append("juz " + ",".join(map(str, self.juz)))
        if self.revelation_order_min or self.revelation_order_max:
            bits.append(
                f"revelation order {self.revelation_order_min or 1}"
                f"–{self.revelation_order_max or 114}"
            )
        return ", ".join(bits) or "whole corpus"
