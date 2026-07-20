"""clitg package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("clitg")
except PackageNotFoundError:
    __version__ = "0.1.0"

SCHEMA_VERSION = "0.1"

__all__ = ["SCHEMA_VERSION", "__version__"]
