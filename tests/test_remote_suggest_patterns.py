from metis.core.codex_session import CodexSession
from metis.core.ctf_remote import RemoteWorkflow


def suggest(tmp_path, text):
    database = tmp_path / "s.sqlite"
    context = CodexSession(database).intake(title="t", description=text, paths=[])
    return RemoteWorkflow(database).suggest(context["run_id"])["candidates"]


def hp(candidates):
    return {(c["host"], c["port"], c["tls"]) for c in candidates}


def test_nc_only_intake_without_artifact_and_variants(tmp_path):
    text = ("nc -v a.example.com 1111\nncat --ssl b.example.com 2222\n"
            "socat - TCP:c.example.com:3333\nsocat TCP:d.example.com:4444 -\n"
            "socat - OPENSSL:e.example.com:5555\n"
            "openssl s_client -connect f.example.com:6666\ntelnet g.example.com 7777\n"
            "nc [::1] 8888\nnc a.example.com 1111")
    result = suggest(tmp_path, text)
    assert hp(result) == {
        ("a.example.com", 1111, False), ("b.example.com", 2222, True),
        ("c.example.com", 3333, False), ("d.example.com", 4444, False),
        ("e.example.com", 5555, True), ("f.example.com", 6666, True),
        ("g.example.com", 7777, False), ("::1", 8888, False)}
    assert len(result) == 8


def test_bare_host_port_needs_context_and_avoids_false_positives(tmp_path):
    result = suggest(tmp_path, "Connect to the server at pwn.example.com:31337\n"
                     "See http://web.example.com:8080/x and the server at https://s.example.com:8443\n"
                     "Meeting at server room 12:30\nport 3.14:99\npwn2.example.com:4000 (no context)\n"
                     "remote [2001:db8::1]:9000")
    assert hp(result) == {("pwn.example.com", 31337, False), ("2001:db8::1", 9000, False)}
