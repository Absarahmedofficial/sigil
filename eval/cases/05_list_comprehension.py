"""Case 05: list comprehension.

main(xs) -> comma-joined string of xs with each element doubled, skipping odd values.
"""
def main(xs):
    doubled_evens = [str(x * 2) for x in xs if x % 2 == 0]
    return ",".join(doubled_evens)
