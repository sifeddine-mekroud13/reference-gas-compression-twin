# 0003. Python tooling: uv workspace, ruff, mypy strict, pytest

- Status: accepted
- Date: 2026-11-08

## Decision
- Python 3.12 pinned (`requires-python = ">=3.12,<3.13"`).
- uv workspace: root `pyproject.toml`, members under `libs/*` (later `services/*`), one `uv.lock`.
- ruff for lint and format (no black). mypy `--strict` on `libs/`.
- pytest. Unit tests live next to each package; integration and system tests in `tests/`.

## Rationale
uv is native to monorepos (workspaces), resolves fast and produces a cross-platform lockfile.
Poetry has no first-class workspace support.

## Consequences
CI runs `uv sync --locked`, so dependency changes must update `uv.lock` in the same commit.
