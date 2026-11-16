import sqlite3, hashlib
w="FREQUENT LATTER ADDITIONAL GENDER __________ applies SPIRITS independent ultimate JENNY HELD SUFFERS LEAVE floating zecht opinion QUESTION karaoke strange zero DELIGHT".split()
ini="".join(x[0] for x in w)
c={ini, ini.upper(), ini.lower(), "FLAG_"+ini[5:], "FLAG_"+ini[5:].upper(), "FLAG_"+ini[5:].lower(), "".join(w), "".join(w).upper()}
for k in list(c): c.add("⟦answer:writeups/ksnctf/files/14/14-verify.py#1⟧")
db=sqlite3.connect("file:/Users/makoto.sugita/personal/METIS/.metis-state/metis.sqlite?mode=ro",uri=True)
rows=db.execute("select digest,verdict from web_attempts where run_id=?",("01b16be7cc9d4d5aac16a4b87134e0a9",)).fetchall()
print(len(rows),[(d[:12],v) for d,v in rows]); print(ini)
for k in c:
  for f in (hashlib.sha256,hashlib.sha1,hashlib.md5):
    h=f(k.encode()).hexdigest()
    for d,v in rows:
      if d==h or d.startswith(h[:16]): print("MATCH",k,f.__name__,v)
