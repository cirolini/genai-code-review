# Eval results — openai-compatible/openai/gpt-oss-120b

| Configuration | Precision | Recall | F1 | Noise rate | Cost / PR | Mean latency |
|---|---|---|---|---|---|---|
| openai-compatible/openai/gpt-oss-120b (budget 5) | 70% | 93% | 0.80 | 83% | n/a | 1.66s |
| openai-compatible/openai/gpt-oss-120b (no budget) | 70% | 93% | 0.80 | 83% | n/a | 1.66s |

## Per case — openai-compatible/openai/gpt-oss-120b

| Case | Seeded | Found | Missed | Spurious | Posted |
|---|---|---|---|---|---|
| `clean_constant_extract` | clean | 0 | 0 | 1 | 1 |
| `clean_docstring` | clean | 0 | 0 | 1 | 1 |
| `clean_import_sort` | clean | 0 | 0 | 0 | 0 |
| `clean_rename` | clean | 0 | 0 | 1 | 1 |
| `clean_test_added` | clean | 0 | 0 | 1 | 1 |
| `clean_typing` | clean | 0 | 0 | 1 | 1 |
| `command_injection` | 1 | 1 | 0 | 0 | 1 |
| `integer_division` | 1 | 1 | 0 | 0 | 1 |
| `leaked_secret` | 1 | 1 | 0 | 0 | 1 |
| `missing_null_check` | 1 | 1 | 0 | 0 | 1 |
| `missing_test` | 1 | 0 | 1 | 1 | 1 |
| `n_plus_one` | 1 | 1 | 0 | 0 | 1 |
| `off_by_one` | 1 | 1 | 0 | 0 | 1 |
| `path_traversal` | 1 | 1 | 0 | 0 | 1 |
| `race_condition` | 1 | 1 | 0 | 0 | 1 |
| `resource_leak` | 1 | 1 | 0 | 0 | 1 |
| `sql_injection` | 1 | 1 | 0 | 0 | 1 |
| `swallowed_exception` | 1 | 1 | 0 | 0 | 1 |
| `timezone_bug` | 1 | 1 | 0 | 0 | 1 |
| `unbounded_query` | 1 | 1 | 0 | 0 | 1 |
| `weak_hash` | 1 | 1 | 0 | 0 | 1 |

**Missed defects**

- `missing_test` — billing/discount.py:11 (test)

**Comments on clean diffs**

- `clean_constant_extract` — major: Potential NameError due to undefined DEFAULT_TIMEOUT
- `clean_docstring` — blocker: Unexpected indentation causing syntax error
- `clean_rename` — major: Renamed function breaks existing imports
- `clean_test_added` — minor: Incorrect expected rounding for 1.005
- `clean_typing` — major: Missing import for Handler type hint may cause NameError
