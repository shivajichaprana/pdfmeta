# Contributing to pdfmeta

Thanks for your interest in improving pdfmeta! Contributions of all kinds are
welcome — bug reports, feature ideas, documentation, and pull requests.

## Development setup

```bash
git clone https://github.com/shivajichaprana/pdfmeta.git
cd pdfmeta
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The package lives under `src/pdfmeta/`; tests live in `tests/`; runnable
samples are in `examples/`.

## Checks

```bash
pip install ruff mypy
pytest --cov            # tests + coverage
ruff check src tests    # lint
ruff format src tests   # format
mypy                    # strict type-check
```

All four must pass before a pull request can be merged. CI runs them across
Python 3.9–3.13 on Linux, macOS, and Windows. Tests import the package from
`src/` via the `pythonpath` setting in `pyproject.toml`, so they run with or
without an editable install. To run the checks automatically on each commit:
`pip install pre-commit && pre-commit install`.

## Making changes

1. Create a branch: `git checkout -b my-change`.
2. Make your change and add or update tests to cover it.
3. Run the checks above and make sure they are green.
4. Update `CHANGELOG.md` under the `Unreleased` heading.
5. Open a pull request describing what changed and why.

## Coding guidelines

- Keep the public API small and well documented with docstrings.
- The document-info dictionary is the source of truth; XMP is kept in sync
  for standard fields only, on a best-effort basis.
- Prefer clear, tested behavior over cleverness.

## Reporting bugs

Please open an issue with the pikepdf version, your Python version, and a
minimal PDF or set of steps that reproduces the problem.
