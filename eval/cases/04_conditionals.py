"""Case 04: conditional logic.

main(n) -> classify n as "neg", "zero", or "pos" based on sign.
"""
def main(n):
    if n < 0:
        return "neg"
    elif n == 0:
        return "zero"
    else:
        return "pos"
