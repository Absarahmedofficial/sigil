(lambda: (lambda: 'Case 19: context manager class.\n\nmain(label) -> use a custom context manager that records enter/exit, return the record.\n')())()

class Recorder:

    def __init__(self, label):
        self.label = label
        self.events = []

    def __enter__(self):
        self.events.append(f'enter:{self.label}')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.events.append(f'exit:{self.label}')
        return False

def main(label):
    with Recorder(label) as r:
        r.events.append('body')
    return '|'.join(r.events)