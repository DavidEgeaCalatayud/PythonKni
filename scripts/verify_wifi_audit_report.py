from __future__ import annotations

import argparse
import sys

from pythonkni.wifi_auditor.service import verify_report_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a PythonKni WiFi Auditor evidence report.")
    parser.add_argument("report", help="Path to the exported JSON report")
    args = parser.parse_args()
    try:
        valid = verify_report_file(args.report)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print("VALID" if valid else "INVALID")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
