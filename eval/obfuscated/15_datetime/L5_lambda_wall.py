(lambda: (lambda: 'Case 15: datetime.\n\nmain(y, m, d) -> format date as "YYYY-MM-DD" and return weekday name.\n')())()
import datetime

def main(y, m, d):
    dt = datetime.date(y, m, d)
    return f"{dt.isoformat()}|{dt.strftime('%A')}"