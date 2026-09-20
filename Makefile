# Development tasks. Everything runs inside the local virtualenv.

VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

PROVIDER ?= openai
MODEL    ?=
SUITE    ?= small
RESULTS  ?= docs/results

REPO ?= cirolini/genai-code-review

.PHONY: help venv install lint test check eval eval-dry eval-compare feedback clean

help:
	@echo "make install       install runtime and dev dependencies"
	@echo "make lint          ruff"
	@echo "make test          pytest"
	@echo "make check         lint + test"
	@echo "make eval-dry      list the eval cases without calling any provider"
	@echo "make eval          run the eval set (costs money; needs an API key)"
	@echo "make eval-compare  eval with and without the comment budget (large suite)"
	@echo "make feedback      what reviewers did with the comments (REPO=owner/name)"

$(VENV):
	python3 -m venv $(VENV)

venv: $(VENV)

install: venv
	$(PIP) install -q -r requirements.txt -r requirements-dev.txt

lint: venv
	$(VENV)/bin/ruff check .

test: venv
	$(VENV)/bin/pytest -q

check: lint test

eval-dry: venv
	$(PY) -m evals.run --dry-run --suite $(SUITE)

# Writes a Markdown table to docs/results/. Sends one request per fixture, so
# this costs real money — see the printed request count before it starts.
eval: venv
	@mkdir -p $(RESULTS)
	$(PY) -m evals.run --provider $(PROVIDER) $(if $(MODEL),--model $(MODEL),) \
		--suite $(SUITE) \
		--out $(RESULTS)/$(PROVIDER).md \
		--json-out $(RESULTS)/$(PROVIDER).json

# The budget cannot bind on the small fixtures — none of them produces more
# than max_comments findings — so this runs the composed multi-file cases.
eval-compare: venv
	@mkdir -p $(RESULTS)
	$(PY) -m evals.run --provider $(PROVIDER) $(if $(MODEL),--model $(MODEL),) \
		--suite large --compare-budget \
		--out $(RESULTS)/$(PROVIDER)-budget-comparison.md

# Reads reactions, replies and thread resolution on comments the action has
# already posted. Read-only, and free: no model is called.
feedback: venv
	$(PY) -m evals.feedback --repo $(REPO)

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__
