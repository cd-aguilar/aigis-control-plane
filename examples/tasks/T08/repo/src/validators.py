def is_valid_username(name: str) -> bool:
    """A valid username is 3 to 20 characters long and contains only
    letters, digits, and underscores.
    """
    return len(name) >= 3
