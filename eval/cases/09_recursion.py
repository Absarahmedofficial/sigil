"""Case 09: recursion (factorial).

main(n) -> n! computed recursively, as a string.
"""
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

def main(n):
    return str(factorial(n))
