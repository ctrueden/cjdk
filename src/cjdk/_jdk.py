# This file is part of cjdk.
# Copyright 2022, Board of Regents of the University of Wisconsin System
# SPDX-License-Identifier: MIT

from pathlib import Path

__all__ = [
    "find_home",
]


def find_home(path, _recursion_depth=2):
    """
    Find the Java home directory within path.

    The path may point to the Java home, or a directory containing it, or (for
    macOS) a directory containing Contents/Home.
    """

    if _looks_like_java_home(path):
        return path
    macos_extra = Path("Contents", "Home")
    if _looks_like_java_home(path / macos_extra):
        return path / macos_extra
    if _recursion_depth > 0:
        subdir = _contains_single_subdir(path)
        if subdir:
            return find_home(subdir, _recursion_depth=_recursion_depth - 1)
    raise RuntimeError(f"{path} does not look like it contains a JDK or JRE")


def _looks_like_java_home(path):
    if not (path / "bin").is_dir():
        return False
    if not (
        (path / "bin" / "java").is_file()
        or (path / "bin" / "java.exe").is_file()
    ):
        return False
    return True


def _contains_single_subdir(path):
    items = list(i for i in path.iterdir() if i.is_dir())
    if len(items) == 1:
        return items[0]
    return None
