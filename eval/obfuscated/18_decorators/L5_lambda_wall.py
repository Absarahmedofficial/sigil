(lambda: (lambda: 'Case 18: decorators.\n\nmain(a, b) -> wrapped_add(a, b) returns "result=N" with timing.\n')())()
import time

def timed(fn):

    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        t1 = time.perf_counter()
        return f'result={result}|ms={(t1 - t0) * 1000:.3f}'
    return wrapper

@timed
def add(a, b):
    return a + b

def main(a, b):
    return add(a, b)