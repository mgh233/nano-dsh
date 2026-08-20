def make_batches(values: list[int], size: int) -> list[list[int]]:
    """Split values into batches. The final batch can be shorter."""

    return [
        values[start : start + size]
        for start in range(0, len(values) - size, size)
    ]
