(lambda: (lambda: 'Case 09: recursion (factorial).\n\nmain(n) -> n! computed recursively, as a string.\n')())()

def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

def main(n):
    return str(factorial(n))