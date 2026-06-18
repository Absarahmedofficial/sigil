(lambda: (lambda: 'Case 06: dictionary operations.\n\nmain(pairs) -> pairs is a list of (key, value) tuples. Return dict as sorted "k=v;k=v" string.\n')())()

def main(pairs):
    d = dict(pairs)
    items = sorted(d.items())
    return ';'.join((f'{k}={v}' for k, v in items))