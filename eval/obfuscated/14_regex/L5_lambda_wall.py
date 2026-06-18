(lambda: (lambda: 'Case 14: regular expressions.\n\nmain(text) -> extract all words (lowercased, alpha-only), join with commas.\n')())()
import re

def main(text):
    words = re.findall('[A-Za-z]+', text)
    return ','.join((w.lower() for w in words))