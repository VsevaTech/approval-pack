#!/usr/bin/env python3
"""Verify an evidence file against the content that was approved.

    python examples/verify_evidence.py evidence.json --file snapshot.pdf
    python examples/verify_evidence.py evidence.json --text-file proposal.txt
    python examples/verify_evidence.py evidence.json          # self-check only

The script is deliberately dependency-free: anyone who receives an evidence
file can run it with a stock Python, without installing Approval Pack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="evidence JSON downloaded from Approval Pack")
    parser.add_argument("--file", type=Path, help="the snapshot file to check")
    parser.add_argument("--text-file", type=Path, help="a file holding the approved text")
    args = parser.parse_args(argv)

    data = json.loads(args.evidence.read_text(encoding="utf-8"))
    recorded = data["snapshot"]["sha256"]
    decided = data.get("decided_snapshot_sha256")

    print(f"Approval ID : {data['approval_id']}")
    print(f"Title       : {data['title']}")
    print(f"Decision    : {data['decision']} at {data['decided_at']}")
    print(f"Reviewer    : {data['reviewer']['name']} <{data['reviewer']['email']}>")
    print(f"SHA-256     : {recorded}")

    failures = 0

    if decided is None:
        print("\n! No decision recorded yet — nothing to verify against.")
    elif decided == recorded:
        print("\nOK  decision hash == snapshot hash (the decided version is this version)")
    else:
        print("\nFAIL decision hash != snapshot hash")
        failures += 1

    target = args.file or args.text_file
    if target is not None:
        actual = sha256_of(target)
        print(f"     {target} -> {actual}")
        if actual == recorded:
            print("OK   the file you have is exactly what was approved")
        else:
            print("FAIL the file you have is NOT what was approved")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
