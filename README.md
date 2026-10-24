# LenMark converter

Convert LenMark 3DS **EMD 3.0** projects to **EMX 3.7**, individually or in
batches. The converter preserves supported geometry, editable text, model
data, and saved processing settings, checks each output, and leaves the
original files unchanged.

An unofficial command-line tool for Windows, macOS, and Linux. Requires
**Python 3.10 or newer** and has no runtime dependencies.

## Quick start with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) once:

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS and Linux**

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal after installation, then convert a file:

```sh
uvx lenmark-converter convert "design.emd" -o "converted"
```

`uvx` (also available as `uv tool run`) fetches the package from PyPI and
runs it in an isolated environment, cached for subsequent runs. uv can download a
compatible Python when needed. You do not need to clone the repository or
create a virtual environment yourself.

## Convert files

These commands work in PowerShell and macOS/Linux shells. Replace the quoted
example paths with your files or folders; keep quotes around paths with spaces.

Convert one file and write a JSON report:

```sh
uvx lenmark-converter convert "design.emd" -o "converted" --report "reports/result.json"
```

Convert a folder and its subfolders, preserving relative folders and filenames:

```sh
uvx lenmark-converter convert "old-projects" --recursive -o "converted" --report "reports/batch.json"
```

Translate and check files without saving converted outputs:

```sh
uvx lenmark-converter convert "old-projects" --recursive -o "converted" --dry-run
```

Inspect an EMX file with the independent binary reader:

```sh
uvx lenmark-converter verify "converted/design.emx"
```

Append `--help` after `convert` to see all conversion options.

For frequent use, you can install a persistent command with uv:

```sh
uv tool install lenmark-converter
lenmark-converter --version
```

If uv says its executable directory is missing from PATH, run
`uv tool update-shell` and reopen your terminal. With the tool installed, use
`lenmark-converter` directly in place of `uvx lenmark-converter` above.

### Output and reports

- Source files are opened read-only. Existing outputs are skipped unless you
  supply `--overwrite`.
- Each output is published atomically after verification. A failed conversion
  produces no partial output and leaves an existing destination unchanged.
  Other files in the batch continue.
- Multiple input paths are supported. Ambiguous destination collisions are
  rejected before conversion starts.
- JSON reports include per-file status and errors, paths, checksums, geometry
  fingerprints, counts, and output sizes. Review paths and embedded names
  before sharing a report publicly.

Exit codes are `0` for success or skipped files, `1` for any per-file failure,
and `2` for invalid arguments or batch setup errors.

## Supported content

- Groups, Beziers, Segments, Rectangles, Ellipses, Delay and rotary commands.
- Pen settings, three Fill slots per entity, cached paths, node flags, IDs,
  names, and processing order.
- Native editable text, font references, matrices, glyph geometry, and
  multiline content.
- Mapped MPLine geometry and model references.
- Empty model archives, cones, cylinders, spheres, and STL meshes.
- Flat bitmap projects, preserving the embedded BMP. LenMark regenerates the
  scan cache from the image and processing settings.

Only EMD 3.0 to EMX 3.7 conversion is supported. Unknown layouts, unsupported
automation, and missing laser settings reject the affected file with a reason.
Attached, warped, rotated, or nonuniform bitmap caches are unsupported.
Power, frequency, timing units, fonts, and machine calibration are not
translated. See the [format reference](https://github.com/Robinfr/lenmark-converter/blob/main/docs/format.md) for details and
compatibility defaults.

### Review in LenMark

Verification checks binary structure and supported coordinates. Open converted
files in LenMark and review Preview and processing settings before marking.

Converted projects retain the projected outlines and hatch paths saved by the
old version. For designs mapped to curved surfaces, detach and reproject the
design onto its 3D model in LenMark3DS, then check Preview. Automatic
reprojection is not implemented.

## Conversion problems

If a conversion fails or the result looks wrong,
[open a conversion issue](https://github.com/Robinfr/lenmark-converter/issues/new?template=conversion-issue.yml).
Describe what you expected, what happened, and how to reproduce it. The form
also asks for your converter/LenMark versions and operating system.

If you can share an example, attach a **ZIP containing the original `.emd`
and converted `.emx`** (if one was produced), plus screenshots showing the
problem. Files and screenshots are optional. GitHub does not accept EMD/EMX
attachments directly, so ZIP them first.

**Issues and attachments are public.** Share only files you are authorized to
make public, remove confidential/customer information, and check screenshots
and reports for identifying details. A minimal example is preferable.

## Contributing

Bug fixes, format research, and reproducible examples are welcome. See
[CONTRIBUTING.md](https://github.com/Robinfr/lenmark-converter/blob/main/CONTRIBUTING.md) for development and test instructions, and
[CHANGELOG.md](https://github.com/Robinfr/lenmark-converter/blob/main/CHANGELOG.md) for release notes.

## License

[MIT](https://github.com/Robinfr/lenmark-converter/blob/main/LICENSE). LenMark converter is an independent project and is not
affiliated with or endorsed by LenMark's vendor.

<details>
<summary>Alternative: install with Python and pip</summary>

## Install with Python instead

Install [Python](https://www.python.org/downloads/) first. These commands
create an isolated environment and install the package from PyPI.

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install lenmark-converter
.venv/Scripts/Activate.ps1
lenmark-converter --version
```

If PowerShell blocks activation, use `.venv/Scripts/lenmark-converter.exe`
instead of `lenmark-converter`. Activation is optional. For the examples above,
replace `uvx lenmark-converter` with this installed command.

### macOS and Linux

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install lenmark-converter
source .venv/bin/activate
lenmark-converter --version
```

If your Linux distribution does not include `venv`, install its Python venv
package first (for example, `python3-venv` on Debian/Ubuntu).

In a new terminal, activate the same environment again or use the executable's
full path (`.venv/bin/lenmark-converter` on macOS/Linux).

Use this installed command in place of `uvx lenmark-converter` in the
examples above.

</details>

<details>
<summary>Alternative: run a downloaded GitHub wheel</summary>

Download the wheel from [GitHub Releases](https://github.com/Robinfr/lenmark-converter/releases/latest).
From the download folder, run:

```sh
uvx --from ./lenmark_converter-0.1.2-py3-none-any.whl lenmark-converter --help
```

Append the same `convert` or `verify` arguments used above instead of `--help`.

</details>
