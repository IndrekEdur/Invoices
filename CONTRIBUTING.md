# Contributing

## Development Rules

- Do not commit real invoice files, bank statements, SQLite databases, generated CSV exports, or logs.
- Keep current application behavior unchanged unless the task explicitly asks for a behavior change.
- Prefer small commits with clear messages.
- Add or update tests when changing extraction, matching, payment, or Merit API logic.
- Keep long-running operations observable with progress or logs.

## Running Tests

From the repository root:

```powershell
$env:PYTHONPATH = "."
python -m unittest discover -s tests
```

With the bundled Codex Python:

```powershell
$env:PYTHONPATH = "."
C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests
```

## Formatting and Linting

The repository includes configuration for Black and Ruff in `pyproject.toml`.

Suggested commands once the tools are installed:

```powershell
black --check .
ruff check .
```

Do not reformat the whole legacy application as part of unrelated tasks.

## Commit Hygiene

Before committing:

```powershell
git status
python -m unittest discover -s tests
```

For foundation/configuration tasks, avoid modifying application Python files unless explicitly requested.

## Documentation

Important project documents:

- `SPECIFICATION.md`: product and behavior specification.
- `ARCHITECTURE_REVIEW.md`: architecture critique and migration plan.
- `ARCHITECTURE.md`: target architecture summary.
- `ROADMAP.md`: staged roadmap.
- `DECISIONS.md`: architecture decisions.
