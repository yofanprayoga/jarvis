"""Files tool package."""

from assistant.tools.files.inspect import (
    calculate_shannon_entropy,
    detect_file_type,
    inspect_file_path,
)
from assistant.tools.files.file_tools import (
    inspect_file_tool,
    read_text_tool,
    backup_file_tool,
)

__all__ = [
    "calculate_shannon_entropy",
    "detect_file_type",
    "inspect_file_path",
    "inspect_file_tool",
    "read_text_tool",
    "backup_file_tool",
]
