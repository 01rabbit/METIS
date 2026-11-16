import re, sys, time
sys.path.insert(0, "/Users/makoto.sugita/personal/METIS/.metis-state/work")
from sha512crypt import sha512_crypt  # copy of 14-sha512crypt.py

html_path = "/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-o2a544ip/00-problem.html"
dict_path = "/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-o2a544ip/.metis-web/166750c76f5f413e9f0a20badff9656f.txt"

with open(html_path, "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

# only take lines from the <pre> block (user00..user20), avoid duplicate og:description meta
pre_start = html.index("<pre>")
pre_block = html[pre_start:]
lines = re.findall(r"user\d\d:\$6\$[^:]+:\d+:\d+:\d+:\d+:::", pre_block)

users = []
seen = set()
for line in lines:
    uid, hashpart = line.split(":", 1)
    if uid in seen:
        continue
    seen.add(uid)
    hashval = hashpart.split(":")[0]
    if "DictionaryIsHere" in hashval:
        continue
    users.append((uid, hashval))

print(f"Found {len(users)} real hash lines", file=sys.stderr)

with open(dict_path, "r", encoding="utf-8", errors="replace") as f:
    words = [w.rstrip("\n") for w in f if w.strip()]

print(f"Dictionary size: {len(words)}", file=sys.stderr)

results = {}
t0 = time.time()
for uid, h in sorted(users):
    parts = h.split("$")
    # parts: ['', '6', 'salt', 'hash']
    salt = parts[2]
    expected = parts[3]
    found = None
    for w in words:
        c = sha512_crypt(w, salt, 5000)
        if c == expected:
            found = w
            break
    results[uid] = found
    print(f"{uid}: {found!r}  (elapsed {time.time()-t0:.1f}s)", flush=True)

print("=== SUMMARY ===")
for uid in sorted(results):
    print(uid, results[uid])
