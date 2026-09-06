# A pinned, self-contained way to run the check - no Python on the host, and the
# same result on a laptop and a build agent.
#
# Build once:
#   docker build -t locheck .
#
# Then run it against a folder of localisation files:
#   docker run --rm -v "$PWD:/files" locheck
#   docker run --rm -v "$PWD:/files" locheck --json
#   docker run --rm -v "$PWD:/files" locheck old.plist new.plist
#
# Exit codes pass through, so this drops into a pipeline unchanged:
#   0 nothing blocking, 1 blockers found, 2 files unreadable.

FROM python:3.12-slim

# Installed at build time rather than at run time, so a CI job does not pay for
# it on every run and does not need network access just to check a file.
WORKDIR /app
COPY pyproject.toml ./
COPY locheck ./locheck
RUN pip install --no-cache-dir .

# The files being checked are mounted here. Discovery looks at the working
# directory, so `docker run -v "$PWD:/files" locheck` with no arguments compares
# the two newest versions it finds, exactly like running it on the host.
WORKDIR /files

# stdout is not a terminal under `docker run` without -t, so the tool prints the
# whole report at once and never waits for a keypress. That is what a pipeline
# needs: a prompt in a CI log is a hang, not a feature.
ENTRYPOINT ["locheck"]
