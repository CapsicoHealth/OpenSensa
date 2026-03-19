# ===========================================================================
# Copyright (C) 2025 CapsicoHealth Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===========================================================================

"""CSV formatting tool — converts structured data to pipe-delimited CSV format."""

import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("opensensa.tools")


def _format_csv_value(value: Any) -> str:
    """Format a single value for CSV output (pipe delimiter, RFC 4180 quoting)."""
    if value is None:
        return ""
    str_value = str(value)
    needs_quotes = (
        "|" in str_value
        or "," in str_value
        or '"' in str_value
        or "\n" in str_value
        or "\r" in str_value
        or str_value != str_value.strip()
        or (len(str_value) > 0 and str_value[0] in "=+-@")
    )
    if needs_quotes:
        escaped_value = str_value.replace('"', '""')
        return f'"{escaped_value}"'
    return str_value


def register(mcp):
    """Register the csv_formatter tool with the given MCP instance."""

    @mcp.tool(
        title="Format Data as CSV",
        description=(
            "Convert structured data into pipe-delimited CSV format. Use when the user "
            "requests tabular data, spreadsheet output, or data export."
        ),
        tags=["formatting", "csv", "data"],
    )
    def format_as_csv(
        data: Union[List[Dict[str, Any]], None] = None,
        columns: Union[List[str], None] = None,
        table_name: str = "",
        rows: Union[List[Dict[str, Any]], None] = None,
        records: Union[List[Dict[str, Any]], None] = None,
    ) -> str:
        """Convert list of dictionaries to pipe-delimited CSV format.

        Args:
            data: List of row dictionaries.
            columns: Optional column order. If None, uses keys from first row.
            table_name: Optional title added as a comment line.
            rows: Alias for data.
            records: Alias for data.
        """
        if data is None:
            data = rows if rows is not None else records
        if data is None:
            return "```csv\n# Error: missing required field 'data'\n```"
        if not data:
            return "```csv\n# No data to display\n```"
        if not isinstance(data, list):
            return "```csv\n# Error: data must be a list of dictionaries\n```"

        if columns is None:
            if not isinstance(data[0], dict):
                return "```csv\n# Error: data items must be dictionaries\n```"
            columns = list(data[0].keys())
        if not columns:
            return "```csv\n# No columns to display\n```"

        csv_lines: list[str] = []
        if table_name:
            csv_lines.append(f"# {table_name}")
        csv_lines.append("|".join(_format_csv_value(col) for col in columns))
        for row in data:
            if not isinstance(row, dict):
                continue
            csv_lines.append("|".join(_format_csv_value(row.get(col)) for col in columns))

        return f"```csv\n{chr(10).join(csv_lines)}\n```"
