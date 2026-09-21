"""
The structured output a review produces, and the code that validates it.

Validation is hand-written rather than delegated to a JSON Schema library for
one reason: when the model gets it wrong, we want to hand the model a precise,
short list of what was wrong so a single repair attempt can fix it. A generic
validator's error text is long, full of schema paths, and expensive to send
back. Keeping it here also avoids another dependency.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

SEVERITIES = ("blocker", "major", "minor", "nit")
CATEGORIES = ("bug", "security", "performance", "maintainability", "test", "style")

# Severity ordering, most serious first, for ranking in Phase 3.
SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITIES)}

MAX_TITLE_LENGTH = 120


@dataclass
class Finding:
    """One thing the reviewer wants to say about one place in the diff."""

    file: str
    line_start: int
    line_end: int
    severity: str
    category: str
    confidence: float
    title: str
    rationale: str
    suggestion: str | None = None
    # Set when placement moved or shortened the model's line range to fit the
    # diff. The suggestion was written for the original lines, so it must not
    # be offered as a one-click change on the new ones.
    relocated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rank(self) -> tuple[int, float]:
        """
        Sort key: severity first, confidence second, both descending.

        Phase 3 spends a fixed comment budget in this order.
        """
        return (SEVERITY_RANK.get(self.severity, len(SEVERITIES)), -self.confidence)


# JSON Schema handed to providers that support structured output natively.
# Kept in sync with the validation below by the tests.
FINDING_PROPERTIES = {
    "file": {
        "type": "string",
        "description": "Repository-relative path, exactly as it appears in the diff.",
    },
    "line_start": {
        "type": "integer",
        "description": "First line of the new file this finding refers to.",
    },
    "line_end": {
        "type": "integer",
        "description": "Last line, equal to line_start for a single line.",
    },
    "severity": {"type": "string", "enum": list(SEVERITIES)},
    "category": {"type": "string", "enum": list(CATEGORIES)},
    "confidence": {
        "type": "number",
        "description": "0 to 1. How sure you are this is real, not stylistic preference.",
    },
    "title": {"type": "string", "description": "One line, under 120 characters."},
    "rationale": {
        "type": "string",
        "description": "Why this matters, concretely. No restating the code.",
    },
    "suggestion": {
        "type": "string",
        "description": "Optional replacement code for exactly these lines.",
    },
}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": FINDING_PROPERTIES,
                "required": [
                    "file",
                    "line_start",
                    "line_end",
                    "severity",
                    "category",
                    "confidence",
                    "title",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


class InvalidFindings(ValueError):
    """The model's output could not be read as findings."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []

    def repair_hint(self) -> str:
        """A short, specific description to send back for one repair attempt."""
        listed = "\n".join(f"- {p}" for p in self.problems[:10])
        return f"{self}\n{listed}" if listed else str(self)


def parse_findings(raw: str) -> list[Finding]:
    """
    Turn a model response into findings.

    Raises InvalidFindings with specific problems, which the caller may use to
    ask the model to fix its own output once.
    """
    payload = _load_json(raw)

    if isinstance(payload, list):
        # Tolerate a bare array; it is a common and harmless deviation.
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("findings")
        if items is None:
            raise InvalidFindings(
                "The JSON object has no `findings` key.",
                [f"Top-level keys present: {sorted(payload)[:10]}"],
            )
    else:
        raise InvalidFindings(f"Expected a JSON object, got {type(payload).__name__}.")

    if not isinstance(items, list):
        raise InvalidFindings(f"`findings` must be an array, got {type(items).__name__}.")

    findings, problems = [], []
    for index, item in enumerate(items):
        try:
            findings.append(_build_finding(item, index))
        except InvalidFindings as exc:
            problems.extend(exc.problems or [str(exc)])

    if problems and not findings:
        raise InvalidFindings("No finding in the response was valid.", problems)
    if problems:
        # Partial success is worth keeping: dropping four good findings because
        # a fifth was malformed serves nobody.
        logger.warning("Discarded %d malformed finding(s): %s", len(problems), problems[:3])

    return findings


def _load_json(raw: str):
    """
    Read JSON from a model response.

    Models wrap JSON in prose or a fenced block often enough that refusing to
    handle it would cost real findings, so a fenced block or a bare object is
    extracted before giving up.
    """
    if not raw or not raw.strip():
        raise InvalidFindings("The model returned an empty response.")

    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fall back to the outermost {...} or [...] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise InvalidFindings(
        "The response was not valid JSON.",
        [f"Response began with: {text[:120]!r}"],
    )


def _build_finding(item, index: int) -> Finding:
    where = f"findings[{index}]"
    problems: list[str] = []

    if not isinstance(item, dict):
        raise InvalidFindings(
            f"{where} is not an object.",
            [f"{where}: expected an object, got {type(item).__name__}"],
        )

    def text_field(name, *, required=True, max_length=None):
        value = item.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                problems.append(f"{where}.{name} is missing or empty")
            return None
        if not isinstance(value, str):
            problems.append(f"{where}.{name} must be a string, got {type(value).__name__}")
            return None
        value = value.strip()
        if max_length and len(value) > max_length:
            value = value[: max_length - 1].rstrip() + "…"
        return value

    file = text_field("file")
    title = text_field("title", max_length=MAX_TITLE_LENGTH)
    rationale = text_field("rationale")
    suggestion = text_field("suggestion", required=False)

    severity = _enum_field(item, "severity", SEVERITIES, where, problems)
    category = _enum_field(item, "category", CATEGORIES, where, problems)

    line_start = _int_field(item, "line_start", where, problems)
    line_end = _int_field(item, "line_end", where, problems, default=line_start)
    confidence = _confidence_field(item, where, problems)

    if problems:
        raise InvalidFindings(f"{where} is not a valid finding.", problems)

    if line_end < line_start:
        line_start, line_end = line_end, line_start

    return Finding(
        file=file,
        line_start=line_start,
        line_end=line_end,
        severity=severity,
        category=category,
        confidence=confidence,
        title=title,
        rationale=rationale,
        suggestion=suggestion,
    )


def _enum_field(item, name, allowed, where, problems):
    value = item.get(name)
    if not isinstance(value, str):
        problems.append(f"{where}.{name} is missing")
        return None
    normalised = value.strip().lower()
    if normalised not in allowed:
        problems.append(f"{where}.{name} must be one of {list(allowed)}, got {value!r}")
        return None
    return normalised


def _int_field(item, name, where, problems, default=None):
    value = item.get(name, default)
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        problems.append(f"{where}.{name} must be an integer")
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    else:
        problems.append(f"{where}.{name} must be an integer, got {value!r}")
        return None

    if parsed < 1:
        problems.append(f"{where}.{name} must be 1 or greater, got {parsed}")
        return None
    return parsed


def _confidence_field(item, where, problems):
    value = item.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                problems.append(f"{where}.confidence must be a number, got {value!r}")
                return None
        else:
            problems.append(f"{where}.confidence must be a number, got {value!r}")
            return None
    if not 0.0 <= float(value) <= 1.0:
        problems.append(f"{where}.confidence must be between 0 and 1, got {value}")
        return None
    return float(value)
