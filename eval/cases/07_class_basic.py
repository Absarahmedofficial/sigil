"""Case 07: basic class.

main(name, age) -> Person(name, age).greet() returns "Hello, {name}! You are {age}."
"""
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

    def greet(self):
        return f"Hello, {self.name}! You are {self.age}."

def main(name, age):
    p = Person(name, age)
    return p.greet()
