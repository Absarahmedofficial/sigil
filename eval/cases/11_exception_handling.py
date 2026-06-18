"""Case 11: exception handling.

main(xs) -> divide 100 by each x; collect "ok=N" or "err=M" where M is the exception class name.
"""
def main(xs):
    out = []
    for x in xs:
        try:
            v = 100 / x
            out.append(f"ok={v:.2f}")
        except ZeroDivisionError:
            out.append("err=ZeroDivisionError")
        except Exception as e:
            out.append(f"err={type(e).__name__}")
    return "|".join(out)
