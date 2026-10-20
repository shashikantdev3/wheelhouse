"""The inventory: which hosts Wheelhouse may reach, and how.

Loaded from a YAML file (default: wheelhouse.yaml). Host keys are pinned in a
known_hosts file; there is no trust-on-first-use.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from wheelhouse.safety.approvals import check_approver_name, parse_public_key

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,62}")
_ADDRESS = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-:]{0,252}")
_USER = re.compile(r"[a-z_][a-z0-9_\-]{0,31}")


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses repeated keys instead of keeping the last one."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"repeated key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


class Host(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    address: str
    port: int = Field(default=22, ge=1, le=65535)
    user: str
    identity_file: Path
    services: tuple[str, ...] = ()
    databases: tuple[str, ...] = ()
    """Databases Wheelhouse may query on this host. When listed, others are refused."""
    role: str = ""

    @field_validator("address")
    @classmethod
    def _address(cls, v: str) -> str:
        if not _ADDRESS.fullmatch(v):
            raise ValueError("address must be a host name or IP address")
        return v

    @field_validator("identity_file")
    @classmethod
    def _identity(cls, v: Path) -> Path:
        text = str(v)
        if any(c in text for c in '"%\n\r') or text.startswith("~"):
            raise ValueError("identity_file must be a plain path (no quotes, %, ~ or line breaks)")
        return v

    @field_validator("user")
    @classmethod
    def _user(cls, v: str) -> str:
        if not _USER.fullmatch(v):
            raise ValueError("user must be a plain Unix user name")
        return v


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actions_per_minute: int = Field(default=30, ge=1, le=600)
    max_output_bytes: int = Field(default=200_000, ge=1_000, le=10_000_000)
    connect_timeout_s: int = Field(default=10, ge=1, le=60)


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    known_hosts: Path
    ledger: Path = Path("ledger/ledger.jsonl")
    state: Path = Path(".wheelhouse")
    """Folder for incidents and approvals waiting to be used."""
    approvers: dict[str, str] = {}
    """Who may approve Touch steps: name -> 'ed25519:<public key>'."""
    sudo_users: frozenset[str] = frozenset({"root"})
    limits: Limits = Limits()
    hosts: dict[str, Host]

    @field_validator("hosts")
    @classmethod
    def _names(cls, v: dict[str, Host]) -> dict[str, Host]:
        for name in v:
            if not _NAME.fullmatch(name):
                raise ValueError(f"host name '{name}' is not allowed")
        return v

    @field_validator("approvers")
    @classmethod
    def _approvers(cls, v: dict[str, str]) -> dict[str, str]:
        for name, key in v.items():
            check_approver_name(name)
            parse_public_key(key)
        return v

    def host(self, name: str) -> Host | None:
        return self.hosts.get(name)

    @classmethod
    def load(cls, path: str | Path) -> Inventory:
        p = Path(path)
        data: Any = yaml.load(p.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506
        if not isinstance(data, dict):
            raise ValueError(f"{p} must contain a mapping")
        inv = cls.model_validate(data)
        base = p.parent
        # Relative paths in the file are relative to the file itself.
        return inv.model_copy(
            update={
                "known_hosts": _rel(base, inv.known_hosts),
                "ledger": _rel(base, inv.ledger),
                "state": _rel(base, inv.state),
                "hosts": {
                    n: h.model_copy(update={"identity_file": _rel(base, h.identity_file)})
                    for n, h in inv.hosts.items()
                },
            }
        )


def _rel(base: Path, p: Path) -> Path:
    return p if p.is_absolute() else (base / p)
