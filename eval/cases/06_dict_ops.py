"""Case 06: dictionary operations.

main(pairs) -> pairs is a list of (key, value) tuples. Return dict as sorted "k=v;k=v" string.
"""
def main(pairs):
    d = dict(pairs)
    items = sorted(d.items())
    return ";".join(f"{k}={v}" for k, v in items)
