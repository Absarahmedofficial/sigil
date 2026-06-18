(lambda: (lambda: 'Case 12: file I/O.\n\nmain(text) -> write text to a temp file, read it back, return "got:{read_back}|len:{N}".\n')())()
import tempfile
import os

def main(text):
    fd, path = tempfile.mkstemp(suffix='.txt')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        with open(path, 'r') as f:
            read_back = f.read()
        return f'got:{read_back}|len:{len(read_back)}'
    finally:
        if os.path.exists(path):
            os.unlink(path)