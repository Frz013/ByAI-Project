import random
import string

def random_str(lenght:int) -> str:
    result = "".join(random.choice(string.ascii_letters) for i in range(lenght))
    return result