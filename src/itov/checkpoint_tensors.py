"""Bounded, dependency-free validation of checkpoint safetensors payloads."""

from __future__ import annotations

import array
import math
import struct
import sys

from itov.catalog import object_fields, require
from itov.comfyui import parse_json


def inspect(path, parameters, cuda):
    expected = {}
    for index, parameter in enumerate(parameters):
        for field in ("weight", "exp_avg", "exp_avg_sq"):
            expected[f"p{index:06d}.{field}"] = ("F32", parameter["shape"])
    expected["rng.cpu"] = ("U8", None)
    if cuda:
        expected["rng.cuda"] = ("U8", None)
    size = path.stat().st_size
    require(8 < size <= 256 * 1024**2, "Checkpoint tensor size outside supported bounds")
    with path.open("rb") as stream:
        length = struct.unpack("<Q", stream.read(8))[0]
        require(2 <= length <= min(4 * 1024**2, size - 8), "Invalid checkpoint tensor header")
        header = parse_json(stream.read(length))
        if not isinstance(header, dict) or set(header) != set(expected):
            raise ValueError("Checkpoint tensor keys differ")
        ranges = []
        for name, (dtype, shape) in expected.items():
            row = header[name]
            object_fields(row, {"dtype", "shape", "data_offsets"}, "checkpoint tensor")
            require(row["dtype"] == dtype, "Checkpoint tensor precision differs")
            if shape is None:
                require(
                    isinstance(row["shape"], list)
                    and len(row["shape"]) == 1
                    and type(row["shape"][0]) is int
                    and 1 <= row["shape"][0] <= 65536,
                    "Invalid RNG tensor shape",
                )
            else:
                require(
                    row["shape"] == shape and all(type(n) is int for n in row["shape"]),
                    "Checkpoint parameter shape differs",
                )
            offsets = row["data_offsets"]
            require(
                isinstance(offsets, list)
                and len(offsets) == 2
                and all(type(n) is int for n in offsets),
                "Invalid checkpoint tensor offsets",
            )
            start, end = offsets
            require(
                0 <= start < end <= size - 8 - length
                and end - start == math.prod(row["shape"]) * (4 if dtype == "F32" else 1),
                "Checkpoint tensor payload differs",
            )
            ranges.append((start, end, dtype, name))
        position = 0
        for start, end, dtype, name in sorted(ranges):
            require(start == position, "Checkpoint tensor payload gaps/overlap")
            stream.seek(8 + length + start)
            remaining = end - start
            while remaining:
                raw = stream.read(min(1024**2, remaining))
                require(bool(raw), "Truncated checkpoint tensor")
                if dtype == "F32":
                    numbers = array.array("I", raw)
                    if sys.byteorder != "little":
                        numbers.byteswap()
                    require(
                        all(n & 0x7F800000 != 0x7F800000 for n in numbers),
                        "Nonfinite checkpoint tensor",
                    )
                    if name.endswith(".exp_avg_sq"):
                        require(
                            all(not n & 0x80000000 or n & 0x7FFFFFFF == 0 for n in numbers),
                            "Negative checkpoint second moment",
                        )
                remaining -= len(raw)
            position = end
        require(position == size - 8 - length, "Trailing checkpoint tensor bytes")
    return {"tensors": len(expected), "bytes": size, "finite_fp32_state": True}
