"""monkeyplug - a little script to censor profanity in audio files."""

from importlib.metadata import PackageNotFoundError, version

from .monkeyplug import (
    DownloadToFile,
    GetCodecs,
    GetMonkeyplugTagged,
    Plugger,
    RunMonkeyPlug,
    SetMonkeyplugTag,
    VoskPlugger,
    WhisperPlugger,
    pairwise,
    scrubword,
)

try:
    __version__ = version("monkeyplug")
except PackageNotFoundError:
    __version__ = None

__all__ = [
    "DownloadToFile",
    "GetCodecs",
    "GetMonkeyplugTagged",
    "Plugger",
    "RunMonkeyPlug",
    "SetMonkeyplugTag",
    "VoskPlugger",
    "WhisperPlugger",
    "pairwise",
    "scrubword",
]
