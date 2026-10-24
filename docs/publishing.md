# Release publishing

GitHub Releases and PyPI distribute the same reviewed wheel and source archive.
The `Publish to PyPI` workflow runs when a GitHub release is published, and
skips publishing if the repository is private. Draft releases do not trigger it.
It downloads the attached files, validates their package name and version
against the release tag, checks source archive metadata, and uploads the files
unchanged using PyPI Trusted Publishing.

## One-time setup

1. Sign in to [PyPI](https://pypi.org/), or create an account and complete its
   email verification and two-factor authentication setup. Use the account
   that should own this project.
2. Check whether [lenmark-converter](https://pypi.org/project/lenmark-converter/)
   is already registered. If another owner has registered it, stop and resolve
   ownership or naming before release; do not silently rename the package.
3. Under your PyPI account's **Publishing** settings, add a pending GitHub
   publisher with these values:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `lenmark-converter` |
   | GitHub owner | `Robinfr` |
   | Repository | `lenmark-converter` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

4. Before the public launch, create the `pypi` environment in the repository's
   GitHub **Settings → Environments**. The workflow uses this environment name
   in its publishing identity. No PyPI API token or password is needed in GitHub.

A pending publisher does not reserve a project name. The first successful
upload creates the project and grants ownership to the PyPI account that
registered the pending publisher. See the official
[pending publisher setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [publishing workflow](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
documentation.

## Prepare and review a release

1. Update `pyproject.toml` and `lenmark_converter.__version__` together, plus
   the changelog and any versioned examples. Use a release tag of `v` followed
   by that exact version (for example, `v0.1.2`). CI derives the expected
   version from the project; the publishing workflow uses its release event's
   tag. Neither workflow requires a version edit.
2. Run the tests and the build/check commands in
   [CONTRIBUTING.md](../CONTRIBUTING.md), including source archive normalization.
3. Run `python3 scripts/check_release.py` to validate against the project's
   current version. To check a release tag explicitly, pass `--tag v0.1.2`.
   The `dist/` directory must contain only the matching universal Python wheel
   and source archive.
4. Inspect both archives for private information and unintended files. Have
   changes reviewed before pushing. Confirm CI passes for the release commit.
5. Create or update a draft GitHub release targeting that exact commit, with
   the matching version tag and the two checked files attached. Review the
   README, issue form, release notes, and downloaded assets.

For the initial launch, keep the repository private and the release in draft
until the maintainer explicitly approves public publication. Do not upload to
PyPI or TestPyPI during this private review.

## Publish after approval

1. Recheck name availability and the Trusted Publisher configuration. If the
   project already exists under your account, configure its normal Trusted
   Publisher rather than registering another pending publisher.
2. Make the repository public after approval. Confirm the `pypi` GitHub
   environment exists, then publish the reviewed draft release. Changing the
   repository visibility alone does not run the publishing workflow.
3. Verify that `Publish to PyPI` succeeds and both files appear on PyPI. A
   missing/mismatched asset or identifying archive metadata stops the upload;
   the workflow never rebuilds or modifies the reviewed distributions.
4. In a fresh uv environment, run `uvx lenmark-converter --version`, convert a
   generic example, and inspect it with `uvx lenmark-converter verify`.

If a PyPI upload fails, inspect the workflow error and resolve it before
re-running the failed publishing job. PyPI versions and filenames cannot be
reused for different content; use a new version when published files need
changes.
