from __future__ import annotations

"""Small credential audit for the repository's current tree and Git history.

Usage:
    python scripts/security_audit.py

The history check is advisory because this project may contain old commits
that need a deliberate history rewrite. It never prints a detected secret.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


KEY_PATTERN = re.compile(
    r"(?im)^[ \t]*(?:ETHERSCAN|BSCSCAN|ARBISCAN|ARBSCAN|BASESCAN|POLYGONSCAN|OPTIMISTIC_ETHERSCAN|COINMARKETCAP|DISCORD_BOT_TOKEN|BINANCE_API_KEY|BINANCE_API_SECRET)[ \t]*=[ \t]*([^#\r\n]+)"
)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?m)^[ \t]*([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PRIVATE_KEY|WEBHOOK_URL))[ \t]*=[ \t]*([^#\r\n]+)"
)
DISCORD_WEBHOOK_PATTERN = re.compile(
    r"https://(?:discord(?:app)?\.com|canary\.discord\.com)/api/webhooks/\d{15,}/[A-Za-z0-9._-]{20,}"
)
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----")
PLACEHOLDERS = {"", "<set locally; never commit>", "your_key_here", "your_token_here", "changeme"}
ALLOWED_TEST_VALUES = {"test-key", "arbscan-alias-key"}


def _tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item for item in completed.stdout.decode("utf-8", errors="ignore").split("\0") if item]


def _looks_like_real_secret(value: str) -> bool:
    value = value.strip().strip('"\'')
    if value in PLACEHOLDERS or value in ALLOWED_TEST_VALUES or value.startswith("<set locally"):
        return False
    if value.startswith(("${", "_env_value(", "os.getenv(", "os.environ", "getenv(")):
        return False
    if value in {"None", "null", "false", "False"}:
        return False
    if "discord.com/api/webhooks/..." in value or "discordapp.com/api/webhooks/..." in value:
        return False
    return bool(value)


def _text_has_secret(text: str) -> bool:
    for match in KEY_PATTERN.finditer(text):
        if _looks_like_real_secret(match.group(1)):
            return True
    for match in SENSITIVE_ASSIGNMENT_PATTERN.finditer(text):
        if _looks_like_real_secret(match.group(2)):
            return True
    return bool(DISCORD_WEBHOOK_PATTERN.search(text) or PRIVATE_KEY_PATTERN.search(text))


def current_tree_findings(root: Path) -> list[str]:
    findings: list[str] = []
    for path in _tracked_files(root):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".sqlite", ".pyc"} or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _text_has_secret(text):
            findings.append(f"{path.relative_to(root).as_posix()}:sensitive-pattern")
    return findings


def history_has_matches(root: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "log", "--all", "-p", "--format=", "--no-ext-diff", "--", "."],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return _text_has_secret(completed.stdout or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit tracked files for committed connector credentials.")
    parser.add_argument("--history", action="store_true", help="also report known historical exposure markers")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    findings = current_tree_findings(root)
    if findings:
        print("Current-tree credential findings:")
        for finding in findings:
            print(f"- {finding}")
    else:
        print("Current tracked tree: no credential assignments detected.")
    if args.history and history_has_matches(root):
        print("History advisory: a sensitive connector pattern remains in Git history; rotate credentials and rewrite history before public release.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
