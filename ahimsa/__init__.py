from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ahimsa")
except PackageNotFoundError:
    __version__ = "unknown"
