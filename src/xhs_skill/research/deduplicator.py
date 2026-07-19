from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from xhs_skill.schemas.research import HotNoteCandidate


def normalize_text(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def text_signature(note: HotNoteCandidate) -> str:
    return hashlib.sha256(normalize_text(f"{note.title}{note.snippet or ''}").encode()).hexdigest()


def similarity(a: HotNoteCandidate, b: HotNoteCandidate) -> float:
    return SequenceMatcher(
        None,
        normalize_text(f"{a.title}{a.snippet or ''}"),
        normalize_text(f"{b.title}{b.snippet or ''}"),
    ).ratio()


def deduplicate(notes: list[HotNoteCandidate], threshold: float = 0.9) -> list[HotNoteCandidate]:
    selected: list[HotNoteCandidate] = []
    urls: set[str] = set()
    signatures: set[str] = set()
    for note in notes:
        canonical = note.canonical_url or note.url
        signature = text_signature(note)
        if canonical in urls or signature in signatures:
            continue
        duplicate = next((item for item in selected if similarity(note, item) >= threshold), None)
        if duplicate:
            note.duplicate_cluster = duplicate.id
            continue
        selected.append(note)
        urls.add(canonical)
        signatures.add(signature)
    return selected
