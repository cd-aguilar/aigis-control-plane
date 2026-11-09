# AIGIS sandbox image (P0 D5): what DockerSandbox runs every command in.
#
# - Base pinned by digest, never by a moving tag.
# - Grading tools pinned to the exact versions of the `dev` extra in
#   pyproject.toml (tests/sandbox/test_sandbox_image.py keeps them equal).
# - Non-root user. DockerSandbox passes --user anyway (host uid:gid, or
#   1000:1000 when the host is root or has no uid, e.g. Windows).
#
# A local build is not reproducible byte for byte, so the reference for a
# given machine is the built image ID, not a registry digest:
#   make sandbox-image
# builds it and records `docker image inspect --format {{.Id}}` in
# sandbox/.image-id. DockerSandbox refuses to run if the tag no longer
# resolves to that ID, and runs the image by ID, not by tag.

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install \
        pytest==9.1.1 \
        pytest-json-report==1.5.0 \
        ruff==0.16.4 \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin aigis

USER 1000:1000
WORKDIR /workspace
