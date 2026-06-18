"""Case 14: regular expressions.

main(text) -> extract all words (lowercased, alpha-only), join with commas.
"""
import re

def main(text):
    words = re.findall(r"[A-Za-z]+", text)
    return ",".join(w.lower() for w in words)
