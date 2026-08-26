class Account:
    def __init__(self, balance: float) -> None:
        self.balance = balance

    def withdraw(self, amount: float) -> None:
        self.balance -= amount
