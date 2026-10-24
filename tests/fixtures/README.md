# Test fixtures

`rectangle.emd` is a generic LenMark EMD 3.0 control file containing a
1 mm square at Z = 120 mm and saved pen settings. It contains no customer
artwork or identifying metadata. Its geometry provides a reproducible input
for conversion and package installation checks.

Other tests construct synthetic model, bitmap, text, and geometry records
in memory. The model tests also retain a minimal, independently captured
181-byte empty native model archive as a format reference. These are data
records, not vendor executable code.
