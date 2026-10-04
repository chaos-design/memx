"""CLI command registration modules."""

from .configuration import register_config_commands
from .graph import register_graph_commands
from .ingest import register_ingest_commands
from .maintenance import register_maintenance_commands
from .memory import register_memory_commands
from .retrieval import register_retrieval_commands
from .server import register_server_commands
from .update import register_update_commands

__all__ = [
    "register_config_commands",
    "register_graph_commands",
    "register_ingest_commands",
    "register_maintenance_commands",
    "register_memory_commands",
    "register_retrieval_commands",
    "register_server_commands",
    "register_update_commands",
]
