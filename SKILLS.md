# Project plumbing

How tests, CI/CD, hooks, dependencies and releases fit together. `Makefile` is the source of truth: CI only runs `make ci`.

| Area | File | Update it when |
| --- | --- | --- |
| Commands | `Makefile` | Any new routine command. Give it a `## description` so `make help` lists it, and add it to `CLAUDE.md` if it is a main one. |
| CI checks | `ci` target in `Makefile` | A new check is needed (for example `web-build` once `web/` has code). Add it to `make ci`, not to the workflow. |
| CI environment | `.github/workflows/ci.yml` | CI needs a new tool or service, or branches with a new prefix need to run CI. |
| Tests | `tests/` (pytest) | Behaviour changes. `pytest` fails if it collects no tests, so keep at least one. |
| Lint and format | ruff, default config | Rules change. Add them under `[tool.ruff]` in `pyproject.toml`. |
| Hooks | `.pre-commit-config.yaml` | Bumping ruff: keep `rev` equal to the ruff version in `uv.lock`. Dependabot does not update this file. |
| Dependencies | `pyproject.toml`, `uv.lock` | `uv add [--dev] <pkg>`. Always commit `uv.lock`. |
| Dependabot | `.github/dependabot.yml` | A new ecosystem or folder appears (npm for `web/`, Docker). |
| Releases | `.github/workflows/release-please.yml`, `release-please-config.json`, `.release-please-manifest.json` | Release behaviour changes. Never edit versions by hand. |

## Rules

- Before finishing plumbing changes, run `make ci`, and `make pre-commit` if hooks changed.
- Pin GitHub Actions to a commit SHA with a `# vX.Y.Z` comment.
- Geocoding tests use a fake session (`tests/test_geocode.py`); no test may call Kartverket or any other network service.
- Commit prefixes drive releases: `feat:` is minor, `fix:` is patch, `feat!:` is major. `docs:`, `test:`, `ci:` and `chore:` alone make no release.

## Known gaps

- Branch addresses are gone from rodekors.no and many branches lack coordinates. `make geocode` fills coordinates from Kartverket place names; see `docs/missing-data-quality.md`.
- Release PRs get no CI run, because pushes made with `GITHUB_TOKEN` do not trigger workflows. If `main` requires the CI check, these PRs cannot merge until the workflow uses a PAT or GitHub App token.
- release-please needs the repo setting "Allow GitHub Actions to create and approve pull requests".
