.PHONY: setup sandbox-image test lint check demo-task demo-security demo clean-evidence

PYTHON ?= python
SANDBOX_IMAGE ?= aigis-sandbox:local

setup:
	pip install -e ".[dev]"
	$(MAKE) --no-print-directory sandbox-image

# P0 D5: builds the sandbox image (sandbox/Dockerfile: base pinned by
# digest, grading tools pinned to the dev extra, non-root) and records its
# image ID in sandbox/.image-id. A local build is not reproducible byte for
# byte, so that ID -- not a registry digest -- is what DockerSandbox checks
# before running anything, and what it runs.
sandbox-image:
	docker build -t $(SANDBOX_IMAGE) sandbox/
	docker image inspect --format '{{.Id}}' $(SANDBOX_IMAGE) > sandbox/.image-id
	@echo "sandbox image ID recorded in sandbox/.image-id"

test:
	pytest -q

lint:
	ruff check .

check: test lint

# Fails on its own first line, before touching the network, if the API key
# is missing -- see docs/DEMO.md / STATUS.md: never hardcode it, always
# read from the environment.
demo-task:
	@test -n "$$ANTHROPIC_API_KEY" || { \
		echo "aigis: ANTHROPIC_API_KEY is not set -- export it before running make demo-task" >&2; \
		exit 3; \
	}
	aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo
	@echo
	@echo "--- T01 decision.json (evidence/<run-id>/decision.json) ---"
	$(PYTHON) scripts/show_last_run.py

# The Security Evaluation Suite (S01-S08) runs the deterministic
# ScriptedProvider mechanism from aigis.evaluation.security_suite -- the
# same one the test suite uses, not a real Claude API call. That is
# deliberate: whether a real LLM falls for an injected instruction is a
# separate, non-deterministic question about the model (see
# security_suite.py's module docstring), and this target exists to
# reproducibly show containment, not to bet tokens on a model's judgment.
# No ANTHROPIC_API_KEY needed here. Exits non-zero if any scenario is not
# contained.
demo-security:
	$(PYTHON) scripts/run_security_eval.py all

demo:
	@test -n "$$ANTHROPIC_API_KEY" || { \
		echo "aigis: ANTHROPIC_API_KEY is not set -- export it before running make demo" >&2; \
		exit 3; \
	}
	@echo "=========================================="
	@echo "Part 1/2 -- functional task (T01, real Claude API)"
	@echo "=========================================="
	@$(MAKE) --no-print-directory demo-task
	@echo
	@echo "=========================================="
	@echo "Part 2/2 -- security evals (S01-S08)"
	@echo "=========================================="
	@sec_output="$$($(MAKE) --no-print-directory demo-security)"; \
	echo "$$sec_output"; \
	echo; \
	echo "=== Summary ==="; \
	$(PYTHON) scripts/show_last_run.py --summary; \
	deny_count=$$(printf '%s\n' "$$sec_output" | grep -c 'DENY --' || true); \
	echo "Security evals (S01-S08): $$deny_count DENY recorded"; \
	printf '%s\n' "$$sec_output" | tail -n 1

clean-evidence:
	@read -p "Delete evidence/ ? [y/N] " confirm && [ "$$confirm" = "y" ] && rm -rf evidence/ || echo "aborted"
