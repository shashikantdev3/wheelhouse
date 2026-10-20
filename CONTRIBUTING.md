# Contributing

Thank you for your interest. Issues, bug reports and ideas are welcome from anyone.

## Code contributions

Because Wheelhouse is offered under a commercial licence as well as the Business Source License, code from outside contributors can only be merged after the contributor agrees to the [Contributor Licence Agreement](CLA.md). The agreement lets the author license your contribution under both licences; you keep the copyright in your work.

Until a signing process is set up, pull requests from outside contributors are kept open for discussion but not merged.

## Before opening a pull request

- Install the hooks once: `uv tool install pre-commit`, then `pre-commit install`. They run gitleaks on every commit and refuse committed virtualenvs. Never commit a secret; if one slips in, rotate it first.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
- New actions need a catalog entry, guard rules and tests. See [docs/safety-model.md](docs/safety-model.md).
- Do not add anything that lets an agent delete, purge, drop, truncate or format.
