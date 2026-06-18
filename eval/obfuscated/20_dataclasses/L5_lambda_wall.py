(lambda: (lambda: 'Case 20: dataclasses.\n\nmain(name, score) -> return dataclass repr with frozen=True attempts to mutate captured.\n')())()
from dataclasses import dataclass, field, asdict

@dataclass(frozen=True)
class Record:
    name: str
    score: int
    tags: list = field(default_factory=list)

def main(name, score):
    rec = Record(name=name, score=score, tags=['a', 'b'])
    d = asdict(rec)
    return f"{rec.name}|{rec.score}|{','.join(d['tags'])}"