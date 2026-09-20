# Eval results — openai-compatible/openai/gpt-oss-120b

| Configuration | Precision | Recall | F1 | Noise rate | Cost / PR | Mean latency |
|---|---|---|---|---|---|---|
| openai-compatible/openai/gpt-oss-120b (budget 5) | 83% | 100% | 0.91 | 100% | n/a | 5.46s |
| openai-compatible/openai/gpt-oss-120b (no budget) | 83% | 100% | 0.91 | 100% | n/a | 5.46s |

## What reached the reviewer

| Configuration | Findings | Posted | Suppressed | Posted precision | Posted recall |
|---|---|---|---|---|---|
| openai-compatible/openai/gpt-oss-120b (budget 5) | 12 | 7 | 5 | 71% | 50% |
| openai-compatible/openai/gpt-oss-120b (no budget) | 12 | 12 | 0 | 83% | 100% |

## Per case — openai-compatible/openai/gpt-oss-120b

| Case | Seeded | Found | Missed | Spurious | Posted |
|---|---|---|---|---|---|
| `large_clean_pr` | clean | 0 | 0 | 2 | 2 |
| `large_mixed_pr` | 10 | 10 | 0 | 0 | 5 |

**Comments on clean diffs**

- `large_clean_pr` — major: Added indented docstring likely causes IndentationError
- `large_clean_pr` — major: Reference to undefined DEFAULT_TIMEOUT
