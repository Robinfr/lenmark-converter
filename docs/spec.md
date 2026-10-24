# Conversion scope

Provide local batch conversion from LenMark 3DS EMD 3.0 to EMX 3.7.
Preserve supported geometry, ordered paths, groups, processing settings,
editable text, and model geometry.

- Keep source files unchanged.
- Reject the entire affected file when its data is unsupported; report why.
- Preserve relative paths during recursive folder conversion and reject
  ambiguous output collisions before conversion.
- Publish verified output atomically; never leave a partial result or damage
  an existing destination on failure.
- Provide per-file JSON reports, checksums, and independent binary/coordinate
  verification. Application acceptance is a separate check in LenMark.
- Keep runtime dependencies empty and provide an installable Python CLI.

The [README](../README.md) describes usage and supported content. The
[format reference](format.md) records the binary mappings and their limits.
