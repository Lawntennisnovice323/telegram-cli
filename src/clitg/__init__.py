"""clitg package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("clitg")
except PackageNotFoundError:
    __version__ = "0.2.0"

SCHEMA_VERSION = "0.2"

__all__ = ["SCHEMA_VERSION", "__version__"]
