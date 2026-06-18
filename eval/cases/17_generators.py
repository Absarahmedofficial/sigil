"""Case 17: generator with yield.

main(n) -> first n Fibonacci numbers joined by "-", computed by a generator.
"""
def fibgen(limit):
    a, b = 0, 1
    count = 0
    while count < limit:
        yield a
        a, b = b, a + b
        count += 1

def main(n):
    return "-".join(str(x) for x in fibgen(n))
