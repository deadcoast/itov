"""Versioned, narrow RGB artifact screens; never a model-quality score."""

from __future__ import annotations

from itov.catalog import require, sha256

VERSION = "rgb-artifacts-1"
PARAMETERS = {
    "flat_channel_span_max": 12,
    "band_min_thickness_per_1024": 16,
    "band_scan_fraction_denominator": 4,
    "boundary_mean_difference_min_milli": 24000,
}
RUBRICS = {
    "constant_frame": "Fail: the entire RGB image is one solid color. Pass: visible variation.",
    "edge_bands": "Fail: visible straight border bars along the outer image edges. "
    "Pass: no such bars. Uncertain: background, snow or another scene surface may be a bar. "
    "Unavailable: no distinguishable interior. Inset frames and internal panel dividers "
    "are outside this rubric. Intent and general image quality are not inferred.",
}


def _line(rgb, width, height, edge, depth):
    if edge in ("top", "bottom"):
        row = depth if edge == "top" else height - 1 - depth
        return rgb[row * width * 3 : (row + 1) * width * 3]
    col = depth if edge == "left" else width - 1 - depth
    return b"".join(rgb[(y * width + col) * 3 : (y * width + col) * 3 + 3] for y in range(height))


def measure(rgb: bytes, width: int, height: int):
    require(
        type(width) is int
        and type(height) is int
        and 1 <= width <= 1024
        and 1 <= height <= 1024
        and isinstance(rgb, bytes)
        and len(rgb) == width * height * 3,
        "Expected bounded complete RGB bytes",
    )
    ranges = [{"min": min(rgb[c::3]), "max": max(rgb[c::3])} for c in range(3)]
    constant = all(row["min"] == row["max"] for row in ranges)
    edges = {}
    for edge in ("top", "bottom", "left", "right"):
        dimension = height if edge in ("top", "bottom") else width
        limit = dimension // PARAMETERS["band_scan_fraction_denominator"]
        minimum = (dimension * PARAMETERS["band_min_thickness_per_1024"] + 1023) // 1024
        low, high = [255] * 3, [0] * 3
        previous = None
        thickness = difference = 0
        for depth in range(limit + 1):
            line = _line(rgb, width, height, edge, depth)
            next_low = [min(low[c], min(line[c::3])) for c in range(3)]
            next_high = [max(high[c], max(line[c::3])) for c in range(3)]
            if any(
                next_high[c] - next_low[c] > PARAMETERS["flat_channel_span_max"] for c in range(3)
            ):
                if previous is not None:
                    difference = sum(abs(a - b) for a, b in zip(previous, line, strict=True))
                    difference = difference * 1000 // len(line)
                break
            if depth == limit:
                break
            low, high, previous = next_low, next_high, line
            thickness += 1
        edges[edge] = {
            "flat_thickness_px": thickness,
            "minimum_thickness_px": minimum,
            "scan_limit_px": limit,
            "boundary_mean_difference_milli": difference,
            "flagged": not constant
            and thickness >= minimum
            and difference >= PARAMETERS["boundary_mean_difference_min_milli"],
        }
    return {
        "channel_ranges_rgb": ranges,
        "edges": edges,
        "judgments": {
            "constant_frame": "fail" if constant else "pass",
            "edge_bands": "unavailable"
            if constant
            else "fail"
            if any(row["flagged"] for row in edges.values())
            else "pass",
        },
        "quality_acceptance": "unavailable",
    }


def controls():
    """Constructed positives, negatives and deliberately difficult known misses.

    These exact 512px RGB probes bypass PNG transport. Real inputs always fully
    decode. The controls do not represent natural-image performance.
    """
    size = 512
    gradient = bytes(v for y in range(size) for x in range(size) for v in (x % 256, y % 256, 64))
    values = [
        ("solid-gray", bytes([128, 128, 128]) * size**2, "fail", "unavailable"),
        ("gradient", gradient, "pass", "pass"),
    ]
    for name, thickness, textured in (
        ("bars-16", 16, False),
        ("bars-4", 4, False),
        ("textured-bars-16", 16, True),
    ):
        rgb = bytearray(gradient)
        for y in (*range(thickness), *range(size - thickness, size)):
            for x in range(size):
                value = 237 if textured and x % 2 else 255
                offset = (y * size + x) * 3
                rgb[offset : offset + 3] = bytes([value]) * 3
        values.append((name, bytes(rgb), "pass", "fail"))
    return [
        {
            "id": name,
            "width": size,
            "height": size,
            "decoded_rgb_sha256": sha256(rgb),
            "reference": {"constant_frame": constant, "edge_bands": bands},
            "measurement": measure(rgb, size, size),
        }
        for name, rgb, constant, bands in values
    ]
