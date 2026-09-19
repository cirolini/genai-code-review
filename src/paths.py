"""
Which files are worth a reviewer's attention.

Lockfiles, generated code, vendored dependencies, snapshots and minified assets
are the bulk of many diffs and almost never the part a human needs to look at.
Sending them to the model costs money and, worse, gives it more surface on
which to find things to say.
"""

import fnmatch
import logging

logger = logging.getLogger(__name__)

# Skipped unless the user overrides `ignore_paths`. Every entry here is a file
# type where a finding is nearly always noise: the content is generated, vendored,
# or not read by humans.
DEFAULT_IGNORE_PATHS = (
    # Dependency lockfiles
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/bun.lockb",
    "**/poetry.lock",
    "**/Pipfile.lock",
    "**/uv.lock",
    "**/Cargo.lock",
    "**/composer.lock",
    "**/Gemfile.lock",
    "**/go.sum",
    "**/packages.lock.json",
    # Vendored and installed dependencies
    "**/vendor/**",
    "**/node_modules/**",
    "**/third_party/**",
    # Generated code
    "**/*.pb.go",
    "**/*_pb2.py",
    "**/*_pb2_grpc.py",
    "**/*.generated.*",
    "**/*.g.dart",
    "**/*.freezed.dart",
    "**/generated/**",
    "**/migrations/**",
    # Test snapshots
    "**/__snapshots__/**",
    "**/*.snap",
    "**/testdata/**",
    "**/*.golden",
    # Minified and built assets
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/dist/**",
    "**/build/**",
    # Binary-ish content that a text review cannot help with
    "**/*.svg",
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
    "**/*.ico",
    "**/*.woff",
    "**/*.woff2",
    "**/*.pdf",
)


def parse_ignore_paths(raw: str | None) -> tuple[str, ...]:
    """
    Read the `ignore_paths` input.

    Accepts newline- or comma-separated globs. An unset value means the
    defaults; an explicitly empty value means ignore nothing, which is how a
    user turns the defaults off.
    """
    if raw is None:
        return DEFAULT_IGNORE_PATHS
    if not raw.strip():
        return ()

    patterns = []
    for line in raw.replace(",", "\n").splitlines():
        pattern = line.strip()
        if pattern and not pattern.startswith("#"):
            patterns.append(pattern)
    return tuple(patterns)


def is_ignored(path: str, patterns) -> bool:
    """
    Whether `path` matches any glob.

    fnmatch does not treat `/` specially, so `**/x` matches at any depth — but
    only where there is something before the slash to match. A root-level
    `package-lock.json` does not match `**/package-lock.json`, which is exactly
    the file the pattern is there for, so a leading `**/` is also tried against
    the bare path.
    """
    if not patterns:
        return False

    basename = path.rsplit("/", 1)[-1]
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # "**/x" must also match "x" at the repository root.
        if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
            return True
        # A pattern with no slash is about the file name, wherever it sits.
        if "/" not in pattern and fnmatch.fnmatch(basename, pattern):
            return True
        # "dir/**" should cover the directory's own entries as well as deeper ones.
        if pattern.endswith("/**") and fnmatch.fnmatch(path, pattern[:-3] + "/*"):
            return True
    return False


def partition(paths, patterns):
    """Split paths into (reviewable, ignored), preserving order."""
    reviewable, ignored = [], []
    for path in paths:
        (ignored if is_ignored(path, patterns) else reviewable).append(path)
    if ignored:
        logger.info("Ignoring %d file(s) matching ignore_paths", len(ignored))
    return reviewable, ignored
