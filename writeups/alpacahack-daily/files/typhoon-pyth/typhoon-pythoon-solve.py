D = [207, 197, 236, 194, 221, 208, 195, 183, 175, 190, 183, 178, 145, 162, 132, 159, 119, 90, 105, 94, 127, 126, 83, 73, 105, 37, 44, 46, 57, 45, 25, 11, 6, 26, 255, 237, 247]
loc = b"eye"  # server.pyc requires its parent directory name to be "eye"
print(''.join(chr(v ^ ((i * 7 + 41 + loc[i % 3]) & 255)) for i, v in enumerate(D)))
