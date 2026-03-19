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

"""Chart.js visualization specification builder."""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger("opensensa.tools")

DEFAULT_COLORS = [
    "rgba(54, 162, 235, 0.8)",
    "rgba(255, 99, 132, 0.8)",
    "rgba(75, 192, 192, 0.8)",
    "rgba(153, 102, 255, 0.8)",
    "rgba(255, 206, 86, 0.8)",
    "rgba(255, 159, 64, 0.8)",
]

VALID_CHART_TYPES = {"line", "bar", "pie", "doughnut", "radar", "scatter", "bubble", "polarArea"}


def register(mcp):
    """Register the generate_visualization tool with the given MCP instance."""

    @mcp.tool(
        title="Visualize Charts",
        description=(
            "Create interactive Chart.js visualizations (line, bar, pie, doughnut, radar, "
            "scatter, bubble, polarArea) from data for rendering in the frontend."
        ),
        tags=["visualization", "charts", "data"],
    )
    def generate_visualization(
        chart_type: Optional[Literal["line", "bar", "pie", "doughnut", "radar", "scatter", "bubble", "polarArea"]] = "bar",
        labels: Optional[List[str]] = None,
        datasets: Optional[List[Dict[str, Any]]] = None,
        title: Optional[str] = None,
        x_axis_title: Optional[str] = None,
        y_axis_title: Optional[str] = None,
        stacked: bool = False,
        show_legend: bool = True,
        legend_position: Literal["top", "bottom", "left", "right"] = "bottom",
    ) -> str:
        """Create a Chart.js spec from data. Returns a ```chart code fence."""

        # --- Defensive validation: recover from missing / invalid fields ---
        errors: list[str] = []
        if not labels or not isinstance(labels, list):
            errors.append("'labels' is required and must be a non-empty list of strings")
        if not datasets or not isinstance(datasets, list):
            errors.append("'datasets' is required and must be a non-empty list of dataset objects (each with 'label' and 'data' keys)")
        if errors:
            error_msg = "generate_visualization validation failed: " + "; ".join(errors)
            logger.error(error_msg)
            return f'{{"error": "{error_msg}"}}'

        # Normalise chart_type — accept None / misspellings gracefully
        if not chart_type or chart_type not in VALID_CHART_TYPES:
            logger.warning(f"Invalid chart_type '{chart_type}', falling back to 'bar'")
            chart_type = "bar"

        try:
            chart_spec: dict[str, Any] = {
                "type": chart_type,
                "data": {"labels": labels, "datasets": []},
                "options": {"responsive": True, "maintainAspectRatio": True, "plugins": {}},
            }

            for idx, dataset in enumerate(datasets):
                ds: dict[str, Any] = {
                    "label": dataset.get("label", f"Dataset {idx + 1}"),
                    "data": dataset.get("data", []),
                }
                if "backgroundColor" not in dataset:
                    if chart_type in ("pie", "doughnut", "polarArea"):
                        ds["backgroundColor"] = DEFAULT_COLORS[: len(labels)]
                    else:
                        ds["backgroundColor"] = DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
                else:
                    ds["backgroundColor"] = dataset["backgroundColor"]

                if "borderColor" not in dataset and chart_type in ("line", "radar"):
                    color = DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
                    ds["borderColor"] = color.replace("0.8)", "1)")
                elif "borderColor" in dataset:
                    ds["borderColor"] = dataset["borderColor"]

                if chart_type == "line":
                    ds["tension"] = dataset.get("tension", 0.4)
                    ds["fill"] = dataset.get("fill", False)

                for key in ("borderWidth", "pointRadius", "pointHoverRadius", "fill", "tension"):
                    if key in dataset:
                        ds[key] = dataset[key]

                chart_spec["data"]["datasets"].append(ds)

            if title:
                chart_spec["options"]["plugins"]["title"] = {
                    "display": True,
                    "text": title,
                    "font": {"size": 16},
                }

            chart_spec["options"]["plugins"]["legend"] = {
                "display": show_legend,
                "position": legend_position,
            }

            if chart_type not in ("pie", "doughnut", "radar", "polarArea"):
                scales: dict[str, Any] = {}
                y_cfg: dict[str, Any] = {"beginAtZero": True}
                if y_axis_title:
                    y_cfg["title"] = {"display": True, "text": y_axis_title}
                if stacked:
                    y_cfg["stacked"] = True
                scales["y"] = y_cfg

                x_cfg: dict[str, Any] = {}
                if x_axis_title:
                    x_cfg["title"] = {"display": True, "text": x_axis_title}
                if stacked:
                    x_cfg["stacked"] = True
                if x_cfg:
                    scales["x"] = x_cfg
                chart_spec["options"]["scales"] = scales

            json_str = json.dumps(chart_spec, indent=2)
            logger.info(f"Generated {chart_type} chart with {len(datasets)} dataset(s)")
            return f"```chart\n{json_str}\n```"

        except Exception as e:
            error_msg = f"Failed to create chart: {e}"
            logger.error(error_msg)
            return f'```chart\n{{"error": "{error_msg}"}}\n```'
