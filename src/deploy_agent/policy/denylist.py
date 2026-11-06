"""The hard denylist: destructive operations the agent must never do.

Nothing overrides this list: not the catalog, not a claimed tier, not AI output.
It errs on the side of blocking. A harmless action that happens to use a banned word is
blocked too, which is the safe direction to be wrong in.
"""

import re
import unicodedata

from deploy_agent.policy.rules import normalize_kind

DENYLISTED_KINDS: frozenset[str] = frozenset(
    {
        "delete_resource",
        "delete_volume",
        "delete_database",
        "drop_database",
        "drop_table",
        "truncate_table",
        "force_push",
        "force_deploy",
        "rotate_credentials",
        "revoke_credentials",
        "destroy_stack",
        "wipe_data",
    }
)

# Matched anywhere inside a word, so "dropdatabase" and "force-push" are caught.
BANNED_STEMS: tuple[str, ...] = (
    "delet",
    "drop",
    "destroy",
    "truncat",
    "purg",
    "wipe",
    "wiping",
    "erase",
    "erasing",
    "force",
    "rotat",
    "revok",
    "nuke",
    "obliterat",
)

# Matched only as whole words, because they are too short to search inside other words.
BANNED_WORDS: frozenset[str] = frozenset({"rm", "rmdir", "rmrf"})

_WORD_SPLIT = re.compile(r"[^0-9a-z]+")


def _words(text: str) -> list[str]:
    """Split text into lowercase words, after removing tricks that hide a word.

    NFKC turns full-width and similar letters into plain ones. Invisible format characters
    (such as zero-width spaces) are dropped so they cannot split a banned word in two.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    visible = "".join(char for char in folded if unicodedata.category(char) != "Cf")
    return [word for word in _WORD_SPLIT.split(visible) if word]


def contains_banned_word(text: str) -> bool:
    return any(
        word in BANNED_WORDS or any(stem in word for stem in BANNED_STEMS) for word in _words(text)
    )


def is_denylisted(kind: str, description: str) -> bool:
    """True when the action kind or its description names a destructive operation."""
    return (
        normalize_kind(kind) in DENYLISTED_KINDS
        or contains_banned_word(kind)
        or contains_banned_word(description)
    )
