# This file is part of cjdk.
# Copyright 2022, Board of Regents of the University of Wisconsin System
# SPDX-License-Identifier: MIT

import json
import re
import warnings
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import _cache
from ._conf import Configuration

__all__ = [
    "jdk_index",
    "available_jdks",
    "resolve_jdk_version",
    "jdk_url",
]


_INDEX_KEY_PREFIX = ("v0", "index")
_INDEX_FILENAME = "jdk-index.json"


def jdk_index(conf: Configuration):
    """
    Get the JDK index, from cache if possible.
    """
    return _read_index(_cached_index(conf))


def available_jdks(index, conf: Configuration):
    """
    Find in index the available JDK vendor-version combinations.

    A list of tuples (vendor, version) is returned.

    Arguments:
    index -- The JDK index (nested dict)
    """
    try:
        # jdks is dict: vendor -> (version -> url)
        jdks = index[conf.os][conf.arch]
    except KeyError:
        return []

    return sorted(
        (vendor.removeprefix("jdk@"), version)
        for vendor, versions in jdks.items()
        for version in versions
    )


def resolve_jdk_version(index, conf: Configuration):
    """
    Find in index the exact JDK version for the given configuration.

    Arguments:
    index -- The JDK index (dested dict)
    """
    jdks = available_jdks(index, conf)
    versions = [i[1] for i in jdks if i[0] == conf.vendor]
    if not versions:
        raise KeyError(
            f"No {conf.vendor} JDK is available for {conf.os}-{conf.arch}"
        )
    matched = _match_version(conf.vendor, versions, conf.version)
    if not matched:
        raise KeyError(
            f"No JDK matching version {conf.version} for {conf.os}-{conf.arch}-{conf.vendor}"
        )
    return matched


def jdk_url(index, conf: Configuration):
    """
    Find in index the URL for the JDK binary for the given vendor and version.

    The returned URL usually has a scheme like tgz+https or zip+https.

    Arguments:
    index -- The JDK index (nested dict)
    """
    matched = resolve_jdk_version(index, conf)
    return index[conf.os][conf.arch][f"jdk@{conf.vendor}"][matched]


def _cached_index(conf):
    cache_key = _INDEX_KEY_PREFIX + _cache.key_for_url(conf.index_url)

    def fetch(dest):
        _fetch_index(dest, conf)

    return _cache.atomic_file(
        cache_key,
        _INDEX_FILENAME,
        fetch,
        ttl=conf.index_ttl,
        cache_dir=conf.cache_dir,
    )


def _fetch_index(dest: Path, conf: Configuration):
    if not conf._allow_insecure_for_testing:
        scheme = urlparse(conf.index_url).scheme
        if scheme != "https":
            raise ValueError("Index URL must be an HTTPS URL")

    response = requests.get(conf.index_url)
    response.raise_for_status()
    # Something is probably wrong if the index is not 7-bit clean. Also by
    # making this assumption there is less to worry about when interpreting
    # the index (and the URLs in it).
    if not response.text.isascii():
        raise ValueError(
            "Index unexpectedly contains non-ASCII characters ({conf.index_url})"
        )
    index = response.json()
    with open(dest, "w", encoding="ascii", newline="\n") as outfile:
        json.dump(index, outfile, indent=2, sort_keys=True)


def _read_index(path):
    with open(path, encoding="ascii", newline="\n") as infile:
        return json.load(infile)


def _match_version(vendor, candidates, requested):
    is_graal = "graalvm" in vendor.lower()
    normreq = _normalize_version(requested, remove_prefix_1=not is_graal)
    normcands = {}
    for candidate in candidates:
        try:
            normcand = _normalize_version(
                candidate, remove_prefix_1=not is_graal
            )
        except ValueError:
            warnings.warn(f"Invalid version '{candidate}' in index; skipped")
            continue  # Skip any non-numeric versions (not expected)
        normcands[normcand] = candidate

    # Find the newest candidate compatible with the request
    match_elems = None
    for normcand in sorted(normcands.keys(), reverse=True):
        if _is_version_compatible_with_spec(normcand, normreq):
            return normcands[normcand]
        if normcand > normreq:
            continue
        break
    raise LookupError(f"No matching version for '{vendor}:{requested}'")


_VER_SEPS = re.compile(r"[.-]")


def _normalize_version(ver, *, remove_prefix_1=False):
    # Normalize requested version and candidates:
    # - Split at dots and dashes (so we don't distinguish between '.' and '-')
    # - Convert elements to integers (so that we require numeric elements and
    #   compare them numerically)
    # - If remove_prefix_1 and first element is 1, remove it (so JDK 1.8 == 8)
    # - Return as tuple of ints (so that we compare lexicographically)
    # - Trailing zero elements are NOT removed, so, e.g., 11 < 11.0 (for the
    #   most part, the index uses versions with the same number of elements
    #   within a given vendor; versions like "11" are outliers)
    # - If suffixed with "+", append "+" to the returned tuple
    is_plus = ver.endswith("+")
    if is_plus:
        ver = ver[:-1]
    if ver:
        norm = re.split(_VER_SEPS, ver)
        try:
            norm = tuple(int(e) for e in norm)
        except ValueError:
            raise ValueError(f"Invalid version string: {ver}")
    else:
        norm = ()
    plus = ("+",) if is_plus else ()
    if remove_prefix_1 and len(norm) and norm[0] == 1:
        return norm[1:] + plus
    return norm + plus


def _is_version_compatible_with_spec(version, spec):
    assert "+" not in version
    is_plus = spec and spec[-1] == "+"
    if is_plus:
        spec = spec[:-1]
        if not len(spec):  # spec was just ("+",)
            return True
        return (
            len(version) >= len(spec)
            and version[: len(spec) - 1] == spec[:-1]
            and version[len(spec) - 1] >= spec[-1]
        )
    return len(version) >= len(spec) and version[: len(spec)] == spec
