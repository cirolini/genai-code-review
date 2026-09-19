"""
Entry point for the code review action.

Reads its configuration from the environment, fetches the pull request, asks
the model for a review and posts the result as a comment.
"""

import logging

from clients.github_client import GithubClient
from config import DEFAULT_MAX_TOKENS, DEFAULT_PROVIDER, DEFAULT_TEMPERATURE
from panel import parse_panel
from paths import parse_ignore_paths
from providers import ProviderError, build_provider
from repo_config import load as load_repo_config
from repo_config import resolve as resolve_setting
from review_run import ReviewSettings, execute
from runlog import write as write_runlog
from utils.helpers import get_env_variable

# Configured once here, in the entry point. Library modules only take a logger.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

def main():
    """
    Run a review for the configured pull request.

    Any provider failure is reported in the pull request itself and then
    re-raised, so the check fails loudly instead of leaving a green tick on a
    review that never happened.
    """
    try:
        env_vars = get_env_vars()
    except ValueError as e:
        logger.error("Environment variable error: %s", e)
        raise

    github_client = GithubClient(env_vars["GITHUB_TOKEN"])
    pr_id = env_vars["GITHUB_PR_ID"]

    try:
        provider = build_provider(
            env_vars["PROVIDER"],
            model=env_vars["MODEL"],
            api_key=env_vars["API_KEY"],
            base_url=env_vars["BASE_URL"],
            temperature=env_vars["TEMPERATURE"],
            max_tokens=env_vars["MAX_TOKENS"],
        )
    except ProviderError as e:
        report_provider_failure(github_client, pr_id, e)
        raise

    language = env_vars.get("LANGUAGE") or "en"
    custom_prompt = env_vars.get("CUSTOM_PROMPT")
    mode = env_vars["MODE"]

    try:
        if mode == "review":
            process_review(
                github_client,
                provider,
                pr_id,
                language,
                custom_prompt,
                settings=ReviewSettings(
                    language=language,
                    custom_prompt=custom_prompt,
                    max_comments=env_vars["MAX_COMMENTS"],
                    min_severity=env_vars["MIN_SEVERITY"],
                    min_confidence=env_vars["MIN_CONFIDENCE"],
                    ignore_paths=env_vars["IGNORE_PATHS"],
                    incremental=env_vars["INCREMENTAL"],
                    panel=env_vars["PANEL"],
                ),
            )
        elif mode == "files":
            process_files(github_client, provider, pr_id, language, custom_prompt)
        elif mode == "patch":
            process_patch(github_client, provider, pr_id, language, custom_prompt)
        else:
            logger.error("Invalid mode. Choose 'review', 'files' or 'patch'.")
            raise ValueError("Invalid mode. Choose 'review', 'files' or 'patch'.")
    except ProviderError as e:
        report_provider_failure(github_client, pr_id, e)
        raise


def report_provider_failure(github_client, pr_id, error):
    """
    Tell the reader what went wrong, in the pull request.

    A silent failure is the worst outcome for a review bot: the check goes red
    somewhere in a log nobody opens, and the pull request looks unreviewed in
    exactly the same way as one the bot approved.
    """
    body = (
        "## Code review did not run\n\n"
        f"The `{error.provider}` provider failed and no review was produced: "
        f"{error}\n\n"
        f"<sub>model: `{error.model}`</sub>"
    )
    try:
        github_client.post_comment(pr_id, body)
    except Exception:  # the original error is what matters, not this one
        logger.exception("Could not post the failure comment; original error follows")


def get_env_vars():
    """
    Read configuration from the environment and `.genai-review.yml`.

    Precedence is action input, then repository config file, then default. The
    workflow is the more specific statement of intent, and a file in the
    repository should not silently override what a workflow asked for.

    The v2 inputs (`openai_model`, `openai_api_key`, `openai_temperature`,
    `openai_max_tokens`) still work and are used whenever their v3 equivalent
    is unset, so a workflow written against v2 keeps running unchanged.

    Raises:
        ValueError: if a required variable is missing or cannot be converted.
    """
    config = load_repo_config()

    def setting(name, key, default=None):
        return resolve_setting(get_env_variable(name, required=False), config, key, default)

    env = {
        "GITHUB_TOKEN": get_env_variable("GITHUB_TOKEN", required=True),
        "GITHUB_PR_ID": _as_int("GITHUB_PR_ID", get_env_variable("GITHUB_PR_ID", required=True)),
        "MODE": setting("MODE", "mode", "review"),
        "LANGUAGE": setting("LANGUAGE", "language", "en"),
        "CUSTOM_PROMPT": setting("CUSTOM_PROMPT", "custom_prompt"),
        "PROVIDER": setting("PROVIDER", "provider", DEFAULT_PROVIDER),
        "BASE_URL": setting("BASE_URL", "base_url") or None,
        "MIN_SEVERITY": str(setting("MIN_SEVERITY", "min_severity", "nit")).strip().lower(),
        "INCREMENTAL": _as_bool(setting("INCREMENTAL", "incremental", True), True),
        "PANEL": _as_panel(setting("PANEL", "panel")),
    }

    env["MAX_COMMENTS"] = _as_int_or(
        "MAX_COMMENTS", setting("MAX_COMMENTS", "max_comments"), 5
    )
    env["MIN_CONFIDENCE"] = _as_float(
        "MIN_CONFIDENCE", setting("MIN_CONFIDENCE", "min_confidence"), 0.0
    )
    env["IGNORE_PATHS"] = _as_ignore_paths(
        get_env_variable("IGNORE_PATHS", required=False), config
    )

    # v3 input first, v2 alias second, config file last.
    env["MODEL"] = _first(
        get_env_variable("MODEL", required=False),
        get_env_variable("OPENAI_MODEL", required=False),
        config.get("model"),
    )
    # api_key is never read from the config file: a credential belongs in a
    # secret, not in a file that can be committed by accident.
    env["API_KEY"] = _first(
        get_env_variable("API_KEY", required=False),
        get_env_variable("OPENAI_API_KEY", required=False),
    )
    env["TEMPERATURE"] = _as_float(
        "TEMPERATURE",
        _first(
            get_env_variable("TEMPERATURE", required=False),
            get_env_variable("OPENAI_TEMPERATURE", required=False),
            config.get("temperature"),
        ),
        DEFAULT_TEMPERATURE,
    )
    env["MAX_TOKENS"] = _as_int_or(
        "MAX_TOKENS",
        _first(
            get_env_variable("MAX_TOKENS", required=False),
            get_env_variable("OPENAI_MAX_TOKENS", required=False),
            config.get("max_tokens"),
        ),
        DEFAULT_MAX_TOKENS,
    )

    if env["MODEL"]:
        logger.info("Model: %s", env["MODEL"])
    return env


def _as_panel(value):
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    return parse_panel(value)


def _as_ignore_paths(input_value, config):
    """
    Action input wins; otherwise the config file; otherwise the defaults.

    parse_ignore_paths distinguishes unset (use defaults) from empty (ignore
    nothing), so None has to be passed through rather than coerced to "".
    """
    if input_value not in (None, ""):
        return parse_ignore_paths(input_value)
    if "ignore_paths" in config:
        return tuple(config["ignore_paths"])
    return parse_ignore_paths(input_value if input_value == "" else None)


def _first(*values):
    """The first value that is set and non-empty."""
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_int(name, value):
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} must be an integer, got {value!r}.") from e


def _as_int_or(name, value, default):
    if value in (None, ""):
        return default
    return _as_int(name, value)


def _as_bool(value, default):
    if value in (None, ""):
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_float(name, value, default):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} must be a number, got {value!r}.") from e


def process_review(github_client, provider, pr_id, language, custom_prompt, settings=None):
    """
    v3's review: filtered, incremental, budgeted, and honest about coverage.

    The provider already built by main() is reused as the first panel member,
    so a single-provider run costs exactly one construction.
    """
    settings = settings or ReviewSettings(language=language, custom_prompt=custom_prompt)

    def build_member(name):
        if name is None or name == provider.name:
            return provider
        return build_provider(name, api_key=None)

    report = execute(github_client, build_member, pr_id, settings)

    runlog_path = get_env_variable("RUNLOG_PATH", required=False) or "genai-review-runlog.json"
    write_runlog(report, runlog_path, pr_id=pr_id)

    logger.info(
        "Review complete: %d posted, %d suppressed, %d file(s) ignored",
        len(report.budget.posted),
        len(report.budget.suppressed),
        len(report.ignored_paths),
    )
    return report


def process_files(github_client, provider, pr_id, language, custom_prompt):
    """
    Process the files changed in the last commit of the pull request.

    Args:
        github_client (GithubClient): The GitHub client instance.
        provider (OpenAIClient): The OpenAI client instance.
        pr_id (int): The pull request ID.
        language (str): The language for the review.
        custom_prompt (str, optional): Custom prompt for the code review.
    """
    logger.info("Processing files for PR ID: %s", pr_id)
    pull_request = github_client.get_pr(pr_id)
    commits = list(pull_request.get_commits())

    if not commits:
        logger.info("No commits found.")
        return

    last_commit = commits[-1]
    analyze_commit_files(github_client, provider, pr_id, last_commit, language, custom_prompt)

def process_patch(github_client, provider, pr_id, language, custom_prompt):
    """
    Process the patch content of a pull request.

    Args:
        github_client (GithubClient): The GitHub client instance.
        provider (OpenAIClient): The OpenAI client instance.
        pr_id (int): The pull request ID.
        language (str): The language for the review.
        custom_prompt (str, optional): Custom prompt for the code review.
    """
    logger.info("Processing patch for PR ID: %s", pr_id)
    patch_content = github_client.get_pr_patch(pr_id)
    if not patch_content:
        logger.info("Patch file does not contain any changes.")
        github_client.post_comment(pr_id, "Patch file does not contain any changes")
        return
    analyze_patch(github_client, provider, pr_id, patch_content, language, custom_prompt)

def analyze_commit_files(github_client, provider, pr_id, commit, language, custom_prompt):
    """
    Analyze all files in a given commit together and post a single comment.

    Args:
        github_client (GithubClient): The GitHub client instance.
        provider (OpenAIClient): The OpenAI client instance.
        pr_id (int): The pull request ID.
        commit (Commit): The commit object.
        language (str): The language for the review.
        custom_prompt (str, optional): Custom prompt for the code review.
    """
    logger.info("Analyzing files in commit: %s", commit.sha)
    files = github_client.get_commit_files(commit)

    combined_content = ""
    for file in files:
        logger.info("Processing file: %s", file.filename)
        content = github_client.get_file_content(commit.sha, file.filename)
        combined_content += f"\n### File: {file.filename}\n```{content}```\n"

    result = provider.review(create_review_prompt(combined_content, language, custom_prompt))
    github_client.post_comment(pr_id, format_review_comment(result))

def analyze_patch(github_client, provider, pr_id, patch_content, language, custom_prompt):
    """
    Analyze the patch content of a pull request and post a single comment.

    Args:
        github_client (GithubClient): The GitHub client instance.
        provider (OpenAIClient): The OpenAI client instance.
        pr_id (int): The pull request ID.
        patch_content (str): The patch content.
        language (str): The language for the review.
        custom_prompt (str, optional): Custom prompt for the code review.
    """
    logger.info("Analyzing patch content for PR ID: %s", pr_id)

    combined_diff = ""
    for diff_text in patch_content.split("diff"):
        if diff_text:
            try:
                file_name = diff_text.split("b/")[1].splitlines()[0]
                logger.info("Processing diff for file: %s", file_name)
                combined_diff += f"\n### File: {file_name}\n```diff\n{diff_text}```\n"
            except (TypeError, ValueError) as e:
                logger.error("Error processing diff for file: %s: %s", file_name, str(e))
                github_client.post_comment(
                    pr_id,
                    f"ChatGPT was unable to process the response about {file_name}: {e!s}"
                )

    review_prompt = create_review_prompt(combined_diff, language, custom_prompt)
    result = provider.review(review_prompt)
    github_client.post_comment(pr_id, format_review_comment(result))

def format_review_comment(result):
    """
    Render a review as a pull request comment.

    The footer names the provider, model and token cost. v2 hardcoded
    "ChatGPT's code review", which is wrong as soon as the reviewer is Claude
    or Gemini — and the reader of a review deserves to know which model wrote
    it and what it cost.
    """
    footer = f"<sub>{result.provider} · `{result.model}`"
    if result.usage.total_tokens is not None:
        footer += (
            f" · {result.usage.input_tokens} in / {result.usage.output_tokens} out tokens"
        )
    footer += f" · {result.latency_s:.1f}s</sub>"
    return f"## Code review\n\n{result.text}\n\n{footer}"


def create_review_prompt(content, language, custom_prompt=None):
    """
    Create a review prompt for the OpenAI API.

    Args:
        content (str): The content of the code to be reviewed.
        language (str): The language for the review.
        custom_prompt (str, optional): Custom prompt for the code review.

    Returns:
        str: The review prompt.
    """
    if custom_prompt:
        logger.info("Using custom prompt: %s", custom_prompt)
        return (
            f"{custom_prompt}\n"
            "### Code\n"
            f"```{content}```\n\n"
            f"Write this code review in the following {language}:\n\n"
        )
    return (
        "Please review the following code for clarity, efficiency, and adherence to "
        "best practices. Identify any areas for improvement, suggest specific "
        "optimizations, and note potential bugs or security vulnerabilities. "
        "Additionally, provide suggestions for how to address the identified issues, "
        "with a focus on maintainability and scalability. Include examples of code "
        "where relevant. Use markdown formatting for your response:\n\n"
        f"Write this code review in the following {language}:\n\n"
        f"Do not write the code or guidelines in the review. Only write the review itself.\n\n"
        f"### Code\n```{content}```\n\n"
        f"### Review Guidelines\n"
        f"1. **Clarity**: Is the code easy to understand?\n"
        f"2. **Efficiency**: Are there any performance improvements?\n"
        f"3. **Best Practices**: Does the code follow standard coding conventions?\n"
        f"4. **Bugs/Security**: Are there any potential bugs or security vulnerabilities?\n"
        f"5. **Maintainability**: Is the code easy to maintain and scale?\n\n"
        f"### Review Example\n"
        f"1. **Issue**: The variable names are not descriptive.\n"
        "   **Suggestion**: Use more descriptive variable names that reflect their "
        "purpose. For example:\n"
        f"   ```python\n"
        f"   # Instead of this:\n"
        f"   x = 5\n"
        f"   # Use this:\n"
        f"   item_count = 5\n"
        f"   ```\n"
        f"2. **Issue**: There is a potential SQL injection vulnerability.\n"
        f"   **Suggestion**: Use parameterized queries to prevent SQL injection. For example:\n"
        f"   ```python\n"
        f"   # Instead of this:\n"
        f"   cursor.execute(f'SELECT * FROM users WHERE username = (username)')\n"
        f"   # Use this:\n"
        f"   cursor.execute('SELECT * FROM users WHERE username = %s', (username,))\n"
        f"   ```"
    )


if __name__ == "__main__":
    main()
