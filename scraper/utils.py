import re


def resolve_path(data, path):
    """
    Safely navigates a dictionary/list using dot notation and indices.
    Example path: 'queries[1].state.data[0].name'
    """
    if not path:
        return None

    # Split by dots, but ignore dots inside brackets (if we ever get that complex)
    parts = re.split(r"\.(?![^\[]*\])", path)

    current = data
    for part in parts:
        try:
            # Check for array index: e.g., "queries[1]"
            match = re.match(r"(.+)\[(\d+)\]", part)
            if match:
                key, idx = match.groups()
                current = current.get(key)[int(idx)]
            else:
                current = current.get(part)
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            return None

    return current
