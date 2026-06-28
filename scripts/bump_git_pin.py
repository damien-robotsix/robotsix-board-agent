#!/usr/bin/env python3
"""Update a git dependency pin in pyproject.toml's [tool.uv.sources] section.

Usage:
    uv run scripts/bump_git_pin.py <package-name> <new-rev>

Example:
    uv run scripts/bump_git_pin.py robotsix-llmio 3da3c4317f4a37c634f6b6a4d549001f6e52be9d

The script finds the source entry for the named package (e.g.
``robotsix-llmio = { git = "...", rev = "..." }``) and replaces the
``rev`` value with *new-rev*.  The surrounding TOML structure — including
any comments above or beside the entry — is preserved.
"""

import re
import sys
from pathlib import Path

PYPROJECT = Path("pyproject.toml")


def bump(package_name: str, new_rev: str) -> bool:
    """Update *package_name*'s rev in [tool.uv.sources] in pyproject.toml.

    Returns ``True`` when an entry was found and updated, ``False``
    when no matching source entry exists (the file is left unchanged).
    """
    content = PYPROJECT.read_text()

    # Match the exact source entry line for *package_name*.
    # The line looks like:
    #   robotsix-llmio = { git = "...", rev = "28b23a848003" }
    #
    # We anchor on start-of-line (possibly indented with whitespace),
    # the package name, then capture everything before the current rev
    # and replace only the quoted rev value.
    pattern = re.compile(
        rf'^(\s*{re.escape(package_name)}\s*=\s*\{{[^}}]*rev\s*=\s*)"[^"]*"',
        re.MULTILINE,
    )

    new_content, count = pattern.subn(rf'\1"{new_rev}"', content, count=1)

    if count == 0:
        print(
            f"bump_git_pin: no matching [tool.uv.sources] entry for "
            f"'{package_name}' — is the package listed?",
            file=sys.stderr,
        )
        return False

    if count > 1:
        print(
            f"bump_git_pin: warning: {count} entries matched for "
            f"'{package_name}' — only the first was updated.",
            file=sys.stderr,
        )

    PYPROJECT.write_text(new_content)
    print(f"bump_git_pin: updated {package_name} rev → {new_rev}")
    return True


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <package-name> <new-rev>", file=sys.stderr)
        sys.exit(2)

    package_name = sys.argv[1]
    new_rev = sys.argv[2]

    if not new_rev.strip():
        print("bump_git_pin: new-rev must not be empty", file=sys.stderr)
        sys.exit(2)

    success = bump(package_name, new_rev)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
