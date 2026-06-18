"""Case 16: collections.Counter.

main(items) -> return top-3 most common items as "item:count,item:count,...".
"""
from collections import Counter

def main(items):
    c = Counter(items)
    top = c.most_common(3)
    return ",".join(f"{k}:{v}" for k, v in top)
