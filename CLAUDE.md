# Project
Scrape data from Red Cross homepage to fetch name of local branches, adresses, activities etc., and use that data to create a beautiful interactive map we deploy in either a webapp or streamlit (Cloudflare as hosting if possible, investigate it as we go).

## Commands

Python ≥3.12, managed with `uv` (never `pip install`; add deps with `uv add <pkg>` or
`uv add --dev <pkg>`). `make help` lists all targets.

```sh
uv sync --all-groups   # install (same as make sync)
make ci                # lock-check + lint + format-check + test — exactly what GitHub Actions runs
make lint / make format / make test
make hooks / make pre-commit
make run
make scrape           # scrape all districts to data/raw/<district>.csv (~2-3 h, resumable)
# List more make commands as project grows here
```

## Working style

- State assumptions before editing.
- If the task is ambiguous, ask one clarifying question.
- Touch only files needed for the requested change. Do not refactor unrelated code unless asked.
- Always use plan mode for complex issues.

## Tests, CI/CD and docs — keep them in step with the code

- Read `SKILLS.md` before changing tests, CI, hooks, Make targets, Dependabot or releases.

## Communication

- Be concise.
- Call out trade-offs when multiple reasonable approaches exist.
- Push back if a safer or smaller approach would meet the goal.
- Be critical of suggestions posed by the user rather than agreeable.

## Git

Never write history. Do not run `git commit`, `git push`, `git merge`, `git rebase`,
`git reset --hard`, or `gh pr create`. Staging is fine: `git add`, `git status`, `git diff`.
When work is done, stage it and write the proposed commit message in the reply for the user to run
themselves. Commit messages use conventional prefixes (`feat:`, `fix:`, `test:`, `docs:`, `ci:`).
Branch flow: feature branch → `main` by pull request (`main` is protected; there is no `dev`
branch). PRs and Dependabot target `main`.
