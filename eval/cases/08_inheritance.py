"""Case 08: class inheritance.

main(kind, name) -> returns sound for Animal/Dog classes.
"""
class Animal:
    def __init__(self, name):
        self.name = name
    def speak(self):
        return f"{self.name} makes a sound."

class Dog(Animal):
    def speak(self):
        return f"{self.name} says woof."

class Cat(Animal):
    def speak(self):
        return f"{self.name} says meow."

def main(kind, name):
    if kind == "dog":
        return Dog(name).speak()
    elif kind == "cat":
        return Cat(name).speak()
    else:
        return Animal(name).speak()
