"""Persona identity metadata for Chimera Memory runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PersonaIdentity:
    persona: str | None
    persona_id: str | None
    persona_name: str | None
    persona_root: Path | None
    personas_dir: Path | None
    shared_root: Path | None
    client: str | None

    @property
    def display_name(self) -> str:
        return self.persona_name or self.persona or "unscoped"

    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.persona and self.persona_name and self.persona != self.persona_name:
            warnings.append("TRANSCRIPT_PERSONA differs from CHIMERA_PERSONA_NAME")
        if self.persona_id and "/" not in self.persona_id:
            warnings.append("CHIMERA_PERSONA_ID should use role/name shape")
        if self.persona_root and not self.persona_root.exists():
            warnings.append("CHIMERA_PERSONA_ROOT does not exist")
        if self.personas_dir and not self.personas_dir.exists():
            warnings.append("CHIMERA_PERSONAS_DIR does not exist")
        if self.shared_root and not self.shared_root.exists():
            warnings.append("CHIMERA_SHARED_ROOT does not exist")
        return warnings


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _persona_name_from_id(persona_id: str | None) -> str | None:
    if not persona_id:
        return None
    parts = [part for part in persona_id.replace("\\", "/").split("/") if part.strip()]
    return parts[-1] if parts else None


def _personas_dir_from_root(persona_root: Path | None, persona_id: str | None) -> Path | None:
    if persona_root is None or not persona_id:
        return None
    depth = len([part for part in persona_id.replace("\\", "/").split("/") if part.strip()])
    current = persona_root
    for _ in range(depth):
        current = current.parent
    return current


def _shared_root_from_personas_dir(personas_dir: Path | None) -> Path | None:
    return personas_dir.parent / "shared" if personas_dir is not None else None


def load_identity_from_env() -> PersonaIdentity:
    """Read non-secret persona identity metadata with conservative derivation.

    Explicit env values always win. Missing persona name/root/shared-root fields
    can be derived from the stable `role/name` persona id or persona root so
    launch configs do not need to repeat the same identity six different ways.
    """
    persona_id = os.environ.get("CHIMERA_PERSONA_ID", "").strip() or None
    persona_root = _env_path("CHIMERA_PERSONA_ROOT")
    personas_dir = _env_path("CHIMERA_PERSONAS_DIR") or _personas_dir_from_root(persona_root, persona_id)
    persona_name = os.environ.get("CHIMERA_PERSONA_NAME", "").strip() or _persona_name_from_id(persona_id)
    shared_root = _env_path("CHIMERA_SHARED_ROOT") or _shared_root_from_personas_dir(personas_dir)
    return PersonaIdentity(
        persona=os.environ.get("TRANSCRIPT_PERSONA", "").strip() or persona_name,
        persona_id=persona_id,
        persona_name=persona_name,
        persona_root=persona_root,
        personas_dir=personas_dir,
        shared_root=shared_root,
        client=os.environ.get("CHIMERA_CLIENT", "").strip() or None,
    )
