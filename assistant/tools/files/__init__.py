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
    propose_edit_tool,
    apply_edit_tool,
    restore_backup_tool,
)
from assistant.tools.files.edit import (
    propose_file_edit,
    apply_file_edit,
    restore_file_backup,
    generate_unified_diff,
)

__all__ = [
    "calculate_shannon_entropy",
    "detect_file_type",
    "inspect_file_path",
    "inspect_file_tool",
    "read_text_tool",
    "backup_file_tool",
    "propose_edit_tool",
    "apply_edit_tool",
    "restore_backup_tool",
    "propose_file_edit",
    "apply_file_edit",
    "restore_file_backup",
    "generate_unified_diff",
]

