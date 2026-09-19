"""
Repository-level configuration: `.genai-review.yml`.

Action inputs live in a workflow file, which means changing `max_comments`
requires editing CI. A repository config file lets the settings sit next to the
code they apply to, and be reviewed like anything else in the repository.

Precedence is action inputs over file, because the workflow is the more
specific statement of intent and because a repository should not be able to
silently override what a workflow explicitly asked for.

The file is parsed with PyYAML's safe loader. It is repository content, so it
is untrusted in the same way the diff is: only known keys are read, values are
coerced to the expected types, and anything unrecognised is ignored with a
warning rather than passed through.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = ".genai-review.yml"

# Only these keys are read. Anything else in the file is ignored.
STRING_KEYS = ("provider", "model", "base_url", "mode", "language", "custom_prompt",
               "min_severity")
INT_KEYS = ("max_tokens", "max_comments")
FLOAT_KEYS = ("temperature", "min_confidence")
BOOL_KEYS = ("incremental",)
LIST_KEYS = ("ignore_paths", "panel")

KNOWN_KEYS = set(STRING_KEYS + INT_KEYS + FLOAT_KEYS + BOOL_KEYS + LIST_KEYS)

# Deliberately absent: api_key. A key belongs in a secret, not in a file in the
# repository, and reading one from here would make it easy to commit by
# accident.
FORBIDDEN_KEYS = {"api_key", "openai_api_key", "github_token", "token"}


def load(path: str | None = None) -> dict:
    """
    Read `.genai-review.yml` if it exists.

    Returns an empty dict when the file is missing, empty, unparseable, or not
    a mapping. A broken config file should not fail somebody's pull request —
    it should be reported and ignored.
    """
    path = path or os.getenv("CONFIG_PATH") or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return {}

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML is unavailable; ignoring %s", path)
        return {}

    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except Exception:
        logger.exception("Could not parse %s; ignoring it", path)
        return {}

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        logger.warning("%s must contain a mapping at the top level; ignoring it", path)
        return {}

    return _coerce(raw, path)


def _coerce(raw: dict, path: str) -> dict:
    config: dict = {}

    for key, value in raw.items():
        name = str(key).strip().lower()

        if name in FORBIDDEN_KEYS:
            logger.warning(
                "%s sets `%s`, which is ignored. Credentials belong in a secret, "
                "not in a file in the repository.",
                path,
                name,
            )
            continue

        if name not in KNOWN_KEYS:
            logger.warning("%s sets unknown key `%s`; ignoring it", path, name)
            continue

        if value is None:
            continue

        try:
            if name in INT_KEYS:
                config[name] = int(value)
            elif name in FLOAT_KEYS:
                config[name] = float(value)
            elif name in BOOL_KEYS:
                config[name] = _as_bool(value)
            elif name in LIST_KEYS:
                config[name] = _as_list(value)
            else:
                config[name] = str(value)
        except (TypeError, ValueError):
            logger.warning("%s sets `%s` to %r, which is the wrong type; ignoring it",
                           path, name, value)

    if config:
        logger.info("Loaded %d setting(s) from %s", len(config), path)
    return config


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_list(value) -> list:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    # A single string, or a newline/comma-separated block.
    return [part.strip() for part in str(value).replace(",", "\n").splitlines() if part.strip()]


def resolve(input_value, config: dict, key: str, default=None):
    """
    Action input first, then the config file, then the default.

    An unset action input arrives as "" rather than absent, so empty counts as
    unset here just as it does everywhere else in this codebase.
    """
    if input_value not in (None, ""):
        return input_value
    if key in config:
        return config[key]
    return default
