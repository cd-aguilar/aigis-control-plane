def apply_discount(price, percent):
    return price - (price * percent // 100)  # regression: should be true division
