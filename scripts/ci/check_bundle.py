"""Reject committed server secrets accidentally emitted into public assets."""

from pathlib import Path
import re
import sys

SECRET_FORMATS = (
    re.compile(rb"\bsb_secret_[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\b(?:postgres(?:ql)?|redis)://[^\s:'\"<>]+:[^\s@'\"<>]+@"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\b"),
)
SERVER_LABELS = (b"SUPABASE_SECRET_KEY", b"SUPABASE_SERVICE_ROLE_KEY", b"SUPABASE_DB_PASSWORD")


def main():
    build = Path("dist")
    if not build.is_dir():
        raise SystemExit("dist/ is missing; run the build before the bundle check.")

    findings = []
    for path in build.rglob("*"):
        if path.suffix not in {".js", ".mjs", ".css", ".html", ".map", ".json"}:
            continue
        content = path.read_bytes()
        if any(label in content for label in SERVER_LABELS) or any(
            pattern.search(content) for pattern in SECRET_FORMATS
        ):
            findings.append(path.as_posix())
    if findings:
        print("Server-only identifiers or credential-shaped values found in:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        raise SystemExit(1)
    print("Built assets contain no detected server-only credential patterns.")


if __name__ == "__main__":
    main()
