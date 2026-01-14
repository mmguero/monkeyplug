"""monkeyplug - a little script to censor profanity in audio files"""

from importlib.metadata import version, PackageNotFoundError

_package_name = __name__

try:
    __version__ = version(_package_name)
except PackageNotFoundError:
    __version__ = None

from .monkeyplug import *  # noqa: F401

__all__ = sorted(
    [
        name
        for name, obj in globals().items()
        if not name.startswith("_") and getattr(obj, "__module__", _package_name).startswith(_package_name + '.')
    ],
    key=str.casefold,
)
