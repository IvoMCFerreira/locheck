# Shortcuts for the things you actually do with this. `make` on its own lists them.
#
# Override any of these:
#   make check OLD=loc_2_0_0.plist NEW=loc_2_1_0.plist

PYTHON ?= python
OLD    ?= localisations_1_2_0.plist
NEW    ?= localisations_1_2_1.plist
IMAGE  ?= locheck

.DEFAULT_GOAL := help
.PHONY: help install dev test run summary json check strict docker docker-run clean

help:  ## List these targets
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install the tool, giving you a `locheck` command
	$(PYTHON) -m pip install -e .

dev:  ## Install it with the test dependencies
	$(PYTHON) -m pip install -e ".[dev]"

test:  ## Run the test suite
	$(PYTHON) -m pytest -q

run:  ## Show the full report (does not fail the build)
	@-$(PYTHON) -m locheck $(OLD) $(NEW) --details

summary:  ## Show just the table
	@-$(PYTHON) -m locheck $(OLD) $(NEW) --summary

json:  ## Print the report as JSON
	@$(PYTHON) -m locheck $(OLD) $(NEW) --json

# The CI gate. Unlike `run` this does not swallow the exit code: 0 nothing
# blocking, 1 blockers found, 2 files unreadable. Nothing else to wire up.
check:  ## Fail if the candidate has blockers (for CI)
	$(PYTHON) -m locheck $(OLD) $(NEW) --details

# Stricter: fails on anything flagged, not just blockers. Useful on a branch you
# want spotless, less useful as a merge gate - the HIGH findings are "confirm
# this was intentional", which is a human call, and a gate that refuses those
# teaches people to skip the gate.
strict:  ## Fail on anything flagged, not just blockers
	$(PYTHON) -m locheck $(OLD) $(NEW) --details --strict

docker:  ## Build the container image
	docker build -t $(IMAGE) .

docker-run:  ## Run the check inside the container against this folder
	docker run --rm -v "$(CURDIR):/files" $(IMAGE) $(OLD) $(NEW)

clean:  ## Remove build and test artefacts
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
