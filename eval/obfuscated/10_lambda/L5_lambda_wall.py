(lambda: (lambda: 'Case 10: lambdas and higher-order functions.\n\nmain(xs, k) -> sort xs, take the top k largest, square each, sum them, return as string.\n')())()

def main(xs, k):
    return str(sum((x * x for x in sorted(xs, reverse=True)[:k])))