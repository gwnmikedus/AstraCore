"""Encryption at rest for EVE tokens (Fernet, key `ASTRACORE_TOKEN_KEY`)."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from astracore import config

log = logging.getLogger("astracore")


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = config.token_key()
    if not key:
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
    return Fernet(key.encode())


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
