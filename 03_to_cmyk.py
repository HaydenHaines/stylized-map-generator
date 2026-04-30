"""
03_to_cmyk.py — Convert RGB print PDF to CMYK via Ghostscript.

Usage:
    python 03_to_cmyk.py --input output/map_PRINT.pdf --icc /path/to/profile.icc
    python 03_to_cmyk.py  # uses paths from config.py (CMYK_ICC_PROFILE must be set)

Requires: Ghostscript  (sudo apt install ghostscript  /  brew install ghostscript)
"""

import argparse
import subprocess
import sys
from pathlib import Path

from config import OUTPUT_DIR, CMYK_ICC_PROFILE


def convert_to_cmyk(input_pdf: str, icc_profile: str, output_pdf: str | None = None) -> str:
    input_path = Path(input_pdf)
    if output_pdf is None:
        output_pdf = str(input_path.with_stem(input_path.stem + '_CMYK'))

    cmd = [
        'gs',
        '-sDEVICE=pdfwrite',
        '-dNOPAUSE', '-dBATCH', '-dQUIET',
        '-sColorConversionStrategy=CMYK',
        '-sProcessColorModel=DeviceCMYK',
        f'-sOutputICCProfile={icc_profile}',
        f'-sOutputFile={output_pdf}',
        input_pdf,
    ]

    print(f"  Converting {input_pdf} → {output_pdf}")
    print(f"  ICC profile: {icc_profile}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: Ghostscript failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)

    size_mb = Path(output_pdf).stat().st_size / 1024 ** 2
    print(f"  ✓  CMYK PDF written: {output_pdf}  ({size_mb:.1f} MB)")
    return output_pdf


def _check_ghostscript() -> None:
    result = subprocess.run(['gs', '--version'], capture_output=True)
    if result.returncode != 0:
        print("ERROR: Ghostscript not found.", file=sys.stderr)
        print("Install: sudo apt install ghostscript  /  brew install ghostscript", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert RGB PDF to CMYK via Ghostscript')
    parser.add_argument('--input', default=str(Path(OUTPUT_DIR) / 'map_PRINT.pdf'),
                        help='Input RGB PDF (default: output/map_PRINT.pdf)')
    parser.add_argument('--icc', default=CMYK_ICC_PROFILE,
                        help='Path to printer ICC profile (overrides config.CMYK_ICC_PROFILE)')
    parser.add_argument('--output', default=None,
                        help='Output CMYK PDF path (default: <input>_CMYK.pdf)')
    args = parser.parse_args()

    if not args.icc:
        print("ERROR: No ICC profile specified.", file=sys.stderr)
        print("Set CMYK_ICC_PROFILE in config.py or pass --icc /path/to/profile.icc", file=sys.stderr)
        sys.exit(1)

    _check_ghostscript()
    convert_to_cmyk(args.input, args.icc, args.output)
