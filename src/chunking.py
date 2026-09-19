"""
Fitting a diff into a context window.

v2 sent the whole patch in one request, so a large pull request either blew the
context window or was silently truncated by the provider. Both are worse than
saying so: a review that covered 30% of a diff and did not mention it is a
review that misleads.

Token counts here are estimates. Each provider tokenises differently and
querying a tokeniser per provider would add dependencies and a network call for
something that only needs to be roughly right — the budget has slack for it.
"""

import logging

logger = logging.getLogger(__name__)

# Rough bytes-per-token for source code. Code tokenises worse than prose
# (punctuation, identifiers, indentation), so this is deliberately pessimistic:
# over-estimating costs an extra chunk, under-estimating costs a truncated
# review the user is not told about.
BYTES_PER_TOKEN = 3.0

# Default budget for the diff portion of one request, in tokens. Well inside
# every current model's window, leaving room for the prompt and the response.
DEFAULT_CHUNK_TOKENS = 60_000

# Refuse rather than pretend beyond this many chunks.
MAX_CHUNKS = 8


def estimate_tokens(text: str) -> int:
    return int(len(text or "") / BYTES_PER_TOKEN) + 1


class Chunk:
    """A slice of the diff that fits in one request."""

    def __init__(self, text: str, paths: list[str]):
        self.text = text
        self.paths = paths

    def __repr__(self):
        return f"<Chunk {len(self.paths)} file(s), ~{estimate_tokens(self.text)} tokens>"


def split_diff_by_file(patch: str) -> list[tuple[str, str]]:
    """
    Split a unified diff into (path, text) per file.

    Splits on the `diff --git` line only when it begins a line, which is what
    v2 got wrong by splitting on the bare word.
    """
    if not patch:
        return []

    sections: list[tuple[str, str]] = []
    current_path = None
    current_lines: list[str] = []

    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_path is not None:
                sections.append((current_path, "".join(current_lines)))
            current_path = _path_from_header(line)
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)

    if current_path is not None:
        sections.append((current_path, "".join(current_lines)))
    return sections


def _path_from_header(line: str) -> str:
    parts = line.strip().split(" b/", 1)
    return parts[1] if len(parts) == 2 else line.strip()


def chunk_diff(
    patch: str,
    *,
    keep_paths=None,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    max_chunks: int = MAX_CHUNKS,
):
    """
    Break a diff into chunks that each fit a request.

    Returns (chunks, skipped_paths, truncated). `truncated` is True when the
    diff needed more chunks than allowed — the caller must say so in the
    summary rather than present a partial review as a complete one.

    A single file larger than the budget is skipped whole rather than cut in
    half: half a file produces confident findings about code whose other half
    the model never saw.
    """
    sections = split_diff_by_file(patch)
    if keep_paths is not None:
        keep = set(keep_paths)
        sections = [(path, text) for path, text in sections if path in keep]

    chunks: list[Chunk] = []
    skipped: list[str] = []
    current_text: list[str] = []
    current_paths: list[str] = []
    current_tokens = 0

    for path, text in sections:
        tokens = estimate_tokens(text)
        if tokens > max_tokens:
            logger.warning("Skipping %s: ~%d tokens exceeds the per-request budget", path, tokens)
            skipped.append(path)
            continue

        if current_tokens + tokens > max_tokens and current_paths:
            chunks.append(Chunk("".join(current_text), current_paths))
            current_text, current_paths, current_tokens = [], [], 0

        current_text.append(text)
        current_paths.append(path)
        current_tokens += tokens

    if current_paths:
        chunks.append(Chunk("".join(current_text), current_paths))

    truncated = len(chunks) > max_chunks
    if truncated:
        dropped = chunks[max_chunks:]
        skipped.extend(path for chunk in dropped for path in chunk.paths)
        chunks = chunks[:max_chunks]
        logger.warning("Diff needed %d chunks; keeping %d", len(chunks) + len(dropped), max_chunks)

    return chunks, skipped, truncated
