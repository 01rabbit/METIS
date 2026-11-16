exec(open('/Users/makoto.sugita/personal/METIS/.metis-state/work/22-solve.py').read().split("n=len(rows)")[0])
import collections
L=[r.lower() for r in rows]
print([len(set(r)) for r in L])
c=collections.Counter(''.join(L)); print(sorted(c.items()))
# case counts per row
print([sum(ch.islower() for ch in r) for r in rows])
print([sum(r[i].islower() for r in rows) for i in range(31)])
# is grid symmetric / antisym
print(sum(L[i][j]==L[j][i] for i in range(31) for j in range(31)))
print(sum(L[i][j]==L[30-j][30-i] for i in range(31) for j in range(31)))
# difference matrices mod 26 between adjacent rows
v=lambda s:[ord(c)-97 for c in s]
for i in range(4): print([(a-b)%26 for a,b in zip(v(L[i]),v(L[i+1]))])
