# first 10-digit prime within consecutive digits of pi (digits after "3." counted from the integer part "3")
def pi_digits(n):
    def arctan_inv(x, one):
        s = t = one // x; x2 = x * x; k = 3; sg = -1
        while t:
            t //= x2; s += sg * (t // k); sg = -sg; k += 2
        return s
    one = 10 ** (n + 10)
    return str(4 * (4 * arctan_inv(5, one) - arctan_inv(239, one)) // 10 ** 10)
def is_prime(n):
    if n < 2: return False
    sp = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    for p in sp:
        if n % p == 0: return n == p
    d, s = n - 1, 0
    while d % 2 == 0: d //= 2; s += 1
    for a in sp:
        x = pow(a, d, n)
        if x in (1, n - 1): continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1: break
        else: return False
    return True
d = pi_digits(2000)
for i in range(len(d) - 10):
    if is_prime(int(d[i:i + 10])):
        print(i, d[i:i + 10]); break
