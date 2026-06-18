"""Case 15: datetime.

main(y, m, d) -> format date as "YYYY-MM-DD" and return weekday name.
"""
import datetime

def main(y, m, d):
    dt = datetime.date(y, m, d)
    return f"{dt.isoformat()}|{dt.strftime('%A')}"
