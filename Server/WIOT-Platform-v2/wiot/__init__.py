"""WIOT Platform v2 — industrial water-IoT ingestion, control and analytics server.

The package keeps the field wire contract of the v1.31 server byte-for-byte
(``wiot/<company>/<region>/<node>/{data,status,cmd}`` topics, AES-128-CBC
framing and the ``messages.proto`` schema) and reads/writes the same SQLite
layout, so deployed nodes and historical data keep working unchanged.
"""

__version__ = "2.0.0"
__all__ = ["__version__"]
