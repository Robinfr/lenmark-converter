# Contributing

Use [GitHub Issues](https://github.com/Robinfr/lenmark-converter/issues) to
discuss bugs, unsupported format features, and proposed changes. For incorrect
conversion output, start with the conversion issue form linked from the README.

## Development setup

Clone the repository with Git. Python 3.10 or newer is required.

```sh
git clone https://github.com/Robinfr/lenmark-converter.git
cd lenmark-converter
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --editable .
python3 -m unittest discover -s tests -v
python3 -m compileall -q lenmark_converter tests scripts
```

On Windows PowerShell, create the environment with `py -3 -m venv .venv`.
Use `.venv/Scripts/python.exe` in place of `python3` for the install and test
commands; activation is unnecessary.

## Changes and test data

- Keep changes focused and explain the resulting behavior in your pull request.
- Preserve originals and reject unsupported data explicitly. Do not silently
  drop unknown fields, entities, model data, or processing settings.
- Add a regression test when fixing conversion behavior. Prefer small synthetic
  records with asymmetric geometry that can expose ordering mistakes.
- Keep customer artwork, private paths, conversion reports, and vendor binaries
  out of Git. The existing rectangle fixture is a generic control; other tests
  construct their records in memory.
- Distinguish binary/coordinate checks from acceptance by LenMark. For format
  changes, explain the serialization evidence and any application checks.
- Keep the converter free of runtime dependencies. Record user-visible changes
  under `Unreleased` in the changelog.

## Build and check the package

```sh
python3 -m pip install build twine
python3 -m build
python3 scripts/normalize_sdist.py
python3 scripts/check_release.py
python3 -m twine check dist/*
python3 -m venv .scratch/package-check
.scratch/package-check/bin/python3 -m pip install dist/lenmark_converter-0.1.2-py3-none-any.whl
.scratch/package-check/bin/python3 scripts/smoke_install.py
```

On Windows, use `.scratch/package-check/Scripts/python.exe` for the last two
commands. The smoke check runs the installed module and executable outside the
checkout, converts the generic fixture, verifies the output, checks dry-run
behavior, and checks that the source is unchanged.

CI uses Linux and Python 3.15 to run tests, check package metadata, and
smoke-check installations of both the wheel and source archive. It also checks
package-name resolution and execution through `uvx` using the built distributions
as a local package index; this does not publish anything to PyPI.
Before a release, inspect archive contents for unintended files and ensure the
package version and `lenmark_converter.__version__` agree. Always normalize the
source archive before sharing it: raw tar headers can contain the build
machine's account name. The helper removes ownership and timestamp metadata
without changing file contents. Release assets come
from `dist/`; publish the wheel and source archive on a matching version tag.


## Publishing

Follow the [release publishing guide](docs/publishing.md) to configure PyPI
Trusted Publishing and publish the reviewed GitHub release assets. Drafts and
releases in private repositories do not publish to PyPI. The repository and
initial release must remain private/draft until the maintainer approves launch.
