"""Encryption at rest for EVE tokens (Fernet, key `ASTRACORE_TOKEN_KEY`).

Key rotation: `ASTRACORE_TOKEN_KEY` may list several keys, comma-separated (MultiFernet). The first one
encrypts; every listed key can decrypt. To rotate, put a new key in front and keep the old one after it
until every stored login is encrypted with the new key: AstraCore re-encrypts all of them when it starts
with more than one key (`db.reencrypt_tokens`). After that restart the old key can be dropped."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from astracore import config

log = logging.getLogger("astracore")


def _keys(raw: str) -> List[str]:
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = _keys(config.token_key())
    if not keys:
        if config.PRODUCTION:
            raise RuntimeError("ASTRACORE_TOKEN_KEY is missing in .env.production")
        key = Fernet.generate_key().decode()
        config.save_env({"ASTRACORE_TOKEN_KEY": key})
        config._ENV["ASTRACORE_TOKEN_KEY"] = key
        msg = ("!" * 78 + "\n"
               f"ASTRACORE_TOKEN_KEY was missing, so a new one was generated and saved to {config.ENV_PATH.name}.\n"
               "Back that file up: if the key is lost, every stored EVE login has to be redone.\n" + "!" * 78)
        log.warning(msg)
        print(msg)
        keys = [key]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def rotating() -> bool:
    """More than one key is configured: a rotation is under way."""
    return len(_keys(config.token_key())) > 1


def encrypt(plain: Optional[str]) -> Optional[str]:
    if plain is None:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None   # wrong key or damaged: treated as "needs login"


def reencrypt(token: Optional[str]) -> Optional[str]:
    """The same secret encrypted with the first (current) key; None if no listed key can read it."""
    if token is None:
        return None
    try:
        return _fernet().rotate(token.encode()).decode()
    except InvalidToken:
        return None
