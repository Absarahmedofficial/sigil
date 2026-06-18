(lambda: (lambda: 'Case 03: loop with accumulator.\n\nmain(xs) -> sum of all numbers in xs, formatted as "sum=N".\n')())()

def main(xs):
    total = 0
    for x in xs:
        total += x
    return f'sum={total}'