"""
Unified diff parsing.

Only one question really matters here: for a given file and line number, may a
review comment be attached there? GitHub rejects a comment on a line that is
not part of the diff, and a rejected comment takes the whole review down with
it — so a finding pointing at an untouched line has to be caught before the
request, not after.

The parser is deliberately small and does not try to reconstruct file contents.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# @@ -oldStart,oldCount +newStart,newCount @@
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


@dataclass
class DiffFile:
    """One file in a diff, and the new-file lines a comment may attach to."""

    path: str
    is_deleted: bool = False
    is_binary: bool = False
    # New-file line numbers that appear in the diff, mapped to whether the line
    # was added (True) or is unchanged context (False).
    commentable_lines: dict[int, bool] = field(default_factory=dict)
    added_line_count: int = 0

    def can_comment_on(self, line: int) -> bool:
        return line in self.commentable_lines

    def nearest_commentable_line(self, line: int) -> int | None:
        """
        The closest line in the diff to `line`, or None if the file has none.

        A model asked for a line number will sometimes be off by one or two,
        usually because it counted from the hunk header. Snapping to the nearest
        line in the same file keeps a real finding rather than discarding it,
        and the distance is reported so the caller can decide.
        """
        if not self.commentable_lines:
            return None
        return min(self.commentable_lines, key=lambda candidate: (abs(candidate - line), candidate))


class ParsedDiff:
    """A parsed unified diff, indexed by file path."""

    def __init__(self, files: list[DiffFile]):
        self.files = files
        self._by_path = {f.path: f for f in files}

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self):
        return iter(self.files)

    def get(self, path: str) -> DiffFile | None:
        return self._by_path.get(path)

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self.files]

    @property
    def total_added_lines(self) -> int:
        return sum(f.added_line_count for f in self.files)


def parse_diff(patch: str) -> ParsedDiff:
    """
    Parse a unified diff.

    v2 split the patch on the bare substring "diff", which also split on the
    word wherever it appeared inside the code under review, and then indexed
    into the fragments — the cause of issue #28. This walks the diff line by
    line instead.
    """
    files: list[DiffFile] = []
    current: DiffFile | None = None
    new_line = 0

    for raw in (patch or "").splitlines():
        header = _DIFF_GIT_RE.match(raw)
        if header:
            current = DiffFile(path=header.group(2))
            files.append(current)
            new_line = 0
            continue

        if current is None:
            continue

        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            current.is_binary = True
            continue

        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current.is_deleted = True
            elif target.startswith("b/"):
                # Trust the +++ header over the diff --git line: it is the one
                # that reflects a rename's destination.
                current.path = target[2:]
                files[-1] = current
            continue

        hunk = _HUNK_RE.match(raw)
        if hunk:
            new_line = int(hunk.group(3))
            continue

        if not new_line:
            continue

        if raw.startswith("+"):
            current.commentable_lines[new_line] = True
            current.added_line_count += 1
            new_line += 1
        elif raw.startswith("-"):
            # Removed lines do not exist in the new file, so nothing to attach to.
            continue
        elif raw.startswith(" ") or raw == "":
            current.commentable_lines[new_line] = False
            new_line += 1
        # Anything else ("\\ No newline at end of file", index lines) is skipped.

    # Rebuild the index, since a +++ header may have renamed a file after it
    # was appended.
    return ParsedDiff(files)
