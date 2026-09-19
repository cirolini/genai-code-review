# Eval results — gemini/gemini-3.8-flash

| Configuration | Precision | Recall | F1 | Noise rate | Cost / PR | Mean latency |
|---|---|---|---|---|---|---|
| gemini/gemini-3.8-flash (budget 5) | 100% | 93% | 0.97 | 0% | $0.0009 | 4.95s |
| gemini/gemini-3.8-flash (no budget) | 100% | 93% | 0.97 | 0% | $0.0009 | 4.95s |

## Per case — gemini/gemini-3.8-flash

| Case | Seeded | Found | Missed | Spurious | Posted |
|---|---|---|---|---|---|
| `clean_constant_extract` | clean | 0 | 0 | 0 | 0 |
| `clean_docstring` | clean | 0 | 0 | 0 | 0 |
| `clean_import_sort` | clean | 0 | 0 | 0 | 0 |
| `clean_rename` | clean | 0 | 0 | 0 | 0 |
| `clean_test_added` | clean | 0 | 0 | 0 | 0 |
| `clean_typing` | clean | 0 | 0 | 0 | 0 |
| `command_injection` | 1 | 1 | 0 | 0 | 1 |
| `integer_division` | 1 | 1 | 0 | 0 | 1 |
| `leaked_secret` | 1 | 1 | 0 | 0 | 1 |
| `missing_null_check` | 1 | 1 | 0 | 0 | 1 |
| `missing_test` | 1 | 0 | 1 | 0 | 0 |
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
