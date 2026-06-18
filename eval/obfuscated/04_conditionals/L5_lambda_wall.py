(lambda: (lambda: 'Case 04: conditional logic.\n\nmain(n) -> classify n as "neg", "zero", or "pos" based on sign.\n')())()

def main(n):
    if n < 0:
        return 'neg'
    elif n == 0:
        return 'zero'
    else:
        return 'pos'