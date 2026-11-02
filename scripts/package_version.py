"""Keep mod versions separate from immutable iOS package revisions."""

import re


def versions(lock, stream):
    version = lock["streams"][stream]["mod"]["version"].removeprefix("v")
    build = lock.get("build", {}).get("version", version)
    if "build" in lock and not re.fullmatch(r"[1-9]\d*\.\d+\.\d+", build):
        raise ValueError("Invalid iOS build number")
    return version, build


def release_version(lock, stream):
    version, build = versions(lock, stream)
    return version + "-" + build if "build" in lock else version
