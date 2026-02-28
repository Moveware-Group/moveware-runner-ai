"""
Figma integration for the AI orchestrator.

Extracts design context from Figma URLs found in Jira story descriptions,
providing layout, color, typography, and component information to the LLM
during code generation.

Requires: FIGMA_ACCESS_TOKEN environment variable (Personal Access Token).
Generate at: https://www.figma.com/developers/api#access-tokens
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


FIGMA_API_BASE = "https://api.figma.com/v1"

FIGMA_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?figma\.com/"
    r"(?:design|file|proto)/"
    r"(?P<file_key>[A-Za-z0-9]+)"
    r"(?:/[^?\s]*)?"
    r"(?:\?[^#\s]*node-id=(?P<node_id>[0-9]+-[0-9]+))?"
)


@dataclass
class FigmaDesignContext:
    """Extracted design information from a Figma node."""
    file_name: str = ""
    node_name: str = ""
    node_type: str = ""
    width: Optional[float] = None
    height: Optional[float] = None
    colors: List[str] = field(default_factory=list)
    fonts: List[str] = field(default_factory=list)
    component_names: List[str] = field(default_factory=list)
    layout_mode: Optional[str] = None
    children_summary: List[str] = field(default_factory=list)
    raw_styles: Dict[str, Any] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Format as context for injection into LLM prompts."""
        parts = [f"**Figma Design Context: {self.node_name or self.file_name}**"]

        if self.node_type:
            parts.append(f"- Type: {self.node_type}")
        if self.width and self.height:
            parts.append(f"- Dimensions: {self.width:.0f} x {self.height:.0f}px")
        if self.layout_mode:
            parts.append(f"- Layout: {self.layout_mode}")
        if self.colors:
            parts.append(f"- Colors: {', '.join(self.colors[:12])}")
        if self.fonts:
            parts.append(f"- Fonts: {', '.join(self.fonts[:6])}")
        if self.component_names:
            parts.append(f"- Components: {', '.join(self.component_names[:15])}")
        if self.children_summary:
            parts.append("- Structure:")
            for child in self.children_summary[:20]:
                parts.append(f"  - {child}")

        return "\n".join(parts)


def _get_token() -> Optional[str]:
    return os.getenv("FIGMA_ACCESS_TOKEN")


def _headers() -> dict:
    token = _get_token()
    if not token:
        return {}
    return {"X-Figma-Token": token}


def extract_figma_urls(text: str) -> List[Dict[str, Optional[str]]]:
    """Extract Figma file keys and node IDs from text."""
    matches = []
    for m in FIGMA_URL_PATTERN.finditer(text):
        file_key = m.group("file_key")
        node_id = m.group("node_id")
        if node_id:
            node_id = node_id.replace("-", ":")
        matches.append({"file_key": file_key, "node_id": node_id, "url": m.group(0)})
    return matches


def _rgba_to_hex(color: Dict[str, float]) -> str:
    r = int(color.get("r", 0) * 255)
    g = int(color.get("g", 0) * 255)
    b = int(color.get("b", 0) * 255)
    a = color.get("a", 1.0)
    if a < 1.0:
        return f"rgba({r}, {g}, {b}, {a:.2f})"
    return f"#{r:02x}{g:02x}{b:02x}"


def _extract_colors(node: Dict[str, Any], colors: set) -> None:
    """Recursively extract colors from a Figma node tree."""
    fills = node.get("fills") or []
    for fill in fills:
        if fill.get("type") == "SOLID" and fill.get("visible", True):
            color = fill.get("color")
            if color:
                colors.add(_rgba_to_hex(color))

    strokes = node.get("strokes") or []
    for stroke in strokes:
        if stroke.get("type") == "SOLID" and stroke.get("visible", True):
            color = stroke.get("color")
            if color:
                colors.add(_rgba_to_hex(color))

    for child in node.get("children") or []:
        _extract_colors(child, colors)


def _extract_fonts(node: Dict[str, Any], fonts: set) -> None:
    """Recursively extract font families from a Figma node tree."""
    style = node.get("style") or {}
    family = style.get("fontFamily")
    if family:
        weight = style.get("fontWeight", "")
        size = style.get("fontSize", "")
        fonts.add(f"{family} {weight} {size}px".strip())

    for child in node.get("children") or []:
        _extract_fonts(child, fonts)


def _extract_components(node: Dict[str, Any], names: set) -> None:
    """Recursively extract component/instance names."""
    if node.get("type") in ("COMPONENT", "INSTANCE", "COMPONENT_SET"):
        name = node.get("name", "")
        if name:
            names.add(name)

    for child in node.get("children") or []:
        _extract_components(child, names)


def _summarize_children(node: Dict[str, Any], depth: int = 0, max_depth: int = 3) -> List[str]:
    """Build a structural summary of the node tree."""
    if depth > max_depth:
        return []

    summaries = []
    for child in node.get("children") or []:
        indent = "  " * depth
        name = child.get("name", "Unnamed")
        node_type = child.get("type", "?")
        abs_box = child.get("absoluteBoundingBox") or {}
        w = abs_box.get("width")
        h = abs_box.get("height")
        size_str = f" ({w:.0f}x{h:.0f})" if w and h else ""
        summaries.append(f"{indent}{node_type}: {name}{size_str}")
        summaries.extend(_summarize_children(child, depth + 1, max_depth))

    return summaries


def fetch_design_context(file_key: str, node_id: Optional[str] = None) -> Optional[FigmaDesignContext]:
    """
    Fetch design context from the Figma API.

    Args:
        file_key: Figma file key (from URL)
        node_id: Optional specific node ID (from URL ?node-id=X-Y)

    Returns:
        FigmaDesignContext with extracted design data, or None on failure
    """
    token = _get_token()
    if not token:
        print("Figma integration skipped: FIGMA_ACCESS_TOKEN not set")
        return None

    try:
        if node_id:
            url = f"{FIGMA_API_BASE}/files/{file_key}/nodes?ids={node_id}"
        else:
            url = f"{FIGMA_API_BASE}/files/{file_key}?depth=3"

        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 403:
            print(f"Figma API: access denied for file {file_key} (check token permissions)")
            return None
        if resp.status_code == 404:
            print(f"Figma API: file {file_key} not found")
            return None
        resp.raise_for_status()
        data = resp.json()

        ctx = FigmaDesignContext()
        ctx.file_name = data.get("name", "")

        if node_id and "nodes" in data:
            node_data = data["nodes"].get(node_id, {})
            document = node_data.get("document", {})
        else:
            document = data.get("document", {})

        ctx.node_name = document.get("name", "")
        ctx.node_type = document.get("type", "")

        abs_box = document.get("absoluteBoundingBox") or {}
        ctx.width = abs_box.get("width")
        ctx.height = abs_box.get("height")

        layout = document.get("layoutMode")
        if layout:
            gap = document.get("itemSpacing", 0)
            padding = document.get("paddingLeft", 0)
            ctx.layout_mode = f"{layout} (gap: {gap}px, padding: {padding}px)"

        colors: set = set()
        _extract_colors(document, colors)
        ctx.colors = sorted(colors)

        fonts: set = set()
        _extract_fonts(document, fonts)
        ctx.fonts = sorted(fonts)

        components: set = set()
        _extract_components(document, components)
        ctx.component_names = sorted(components)

        ctx.children_summary = _summarize_children(document)

        return ctx

    except requests.RequestException as e:
        print(f"Figma API error: {e}")
        return None
    except Exception as e:
        print(f"Figma integration error: {e}")
        return None


def get_design_context_for_issue(description: str) -> str:
    """
    Extract Figma URLs from an issue description and fetch design context.

    Returns formatted context string for LLM prompt injection,
    or empty string if no Figma URLs found or API unavailable.
    """
    if not _get_token():
        return ""

    urls = extract_figma_urls(description or "")
    if not urls:
        return ""

    contexts = []
    for url_info in urls[:3]:  # Limit to 3 URLs per issue
        ctx = fetch_design_context(url_info["file_key"], url_info["node_id"])
        if ctx:
            contexts.append(ctx.to_prompt_context())

    if not contexts:
        return ""

    return (
        "\n\n---\n\n"
        "**Design Reference (from Figma):**\n\n"
        + "\n\n".join(contexts)
        + "\n\n**IMPORTANT:** Match the Figma design as closely as possible - "
        "use the specified colors, fonts, dimensions, and component structure.\n"
    )
