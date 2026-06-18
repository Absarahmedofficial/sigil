(lambda: (lambda: 'Case 13: JSON round-trip.\n\nmain(obj) -> json.dumps then json.loads, return "type={T}|keys={K}".\n')())()
import json

def main(obj):
    s = json.dumps(obj, sort_keys=True)
    parsed = json.loads(s)
    if isinstance(parsed, dict):
        keys = ','.join(sorted(parsed.keys()))
        return f'type=dict|keys={keys}'
    elif isinstance(parsed, list):
        return f'type=list|len={len(parsed)}'
    else:
        return f'type={type(parsed).__name__}'