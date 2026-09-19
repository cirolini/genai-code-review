"""
Defaults for the action, in one place.

Model IDs are deliberately not scattered across the provider adapters. When a
provider retires a model, this is the only file that needs to change.

Every ID below was checked against the provider's own documentation on
2026-09-19. Do not add an ID here without checking it the same way — a model
name that looks plausible but does not exist fails at request time, in the
user's pull request, with an error they cannot act on.
"""

# Provider identifiers accepted by the `provider` input.
OPENAI = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"
OPENAI_COMPATIBLE = "openai-compatible"

PROVIDERS = (OPENAI, ANTHROPIC, GEMINI, OPENAI_COMPATIBLE)

# Default model per provider.
#
# These are cost-conscious choices rather than each provider's most capable
# model: the action runs on every push to every pull request, and the person
# paying is whoever installed it. Anyone who wants a stronger reviewer sets
# `model` explicitly.
DEFAULT_MODELS = {
    OPENAI: "gpt-5.6-luna",
    ANTHROPIC: "claude-sonnet-5",
    GEMINI: "gemini-3.8-flash",
    # An OpenAI-compatible endpoint can serve anything; there is no sane
    # default, so `model` is required when this provider is selected.
    OPENAI_COMPATIBLE: None,
}

# Environment variable consulted for a provider's key when `api_key` is unset.
API_KEY_ENV_VARS = {
    OPENAI: "OPENAI_API_KEY",
    ANTHROPIC: "ANTHROPIC_API_KEY",
    GEMINI: "GEMINI_API_KEY",
    OPENAI_COMPATIBLE: "OPENAI_API_KEY",
}

# Gemini is the default because it is the provider this project has actually
# verified end to end: 21/21 eval cases, 100% precision, 0% noise, under a tenth
# of a cent per pull request. See docs/results/.
#
# A v2 workflow that passes `openai_api_key` and no `provider` still gets
# OpenAI — see _resolve_provider in main.py. Sending an OpenAI key to Gemini
# because a default moved would be a silent break, not an upgrade.
DEFAULT_PROVIDER = GEMINI

DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 2048

# Per-request timeout, in seconds.
DEFAULT_TIMEOUT = 120.0

# Retry policy for transient provider failures (timeouts, rate limits, 5xx).
# Deliberately modest: a pull request check that retries for minutes is worse
# than one that fails with a clear message.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 20.0
