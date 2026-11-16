from metis.play_tui import LOGO, Inventory, cells, compose, fit, wrap


def _inventory():
    contest = {"contest_id": "c" * 32, "name": "AlpacaHack Daily", "platform": "alpacahack",
               "url": "https://alpacahack.com/daily", "configured": False, "total": 29, "score": 77.5,
               "counts": {"solved": 27, "handoff": 1, "queued": 1}, "running": True,
               "rules_text": ["提出方法: ブラウザのフォームで提出し metis web attest", "注意: " + "長い注意書き" * 20],
               "last_refresh": None}
    return Inventory(version="0.0.1", revision="abc1234", tools={"claude": True, "tmux": False}, sandbox=True,
                     techniques=75, contests=[contest])


def _text(ops):
    return "\n".join(text for *_, text, _ in ops)


def test_full_screen_has_logo_status_panes_and_keys():
    ops = compose(_inventory(), 0, 3, 112, 34, now=0)
    text = _text(ops)
    assert LOGO[0] in text and "Problem-Solving Intelligence" in text and "Observe · Reason" in text
    assert "CTF" not in text.split("v0.0.1")[0]
    assert "v0.0.1 · abc1234" in text and "MUNIN 75 cards" in text and "1 contests" in text
    assert "▶ AlpacaHack Daily" in text and "⇄1" in text and "27/29" in text and "+ 新しい大会" in text
    assert "93%" in text and "推定・未保存" in text and "tmux で実行中" in text and "引き継ぎ待ち 1 問" in text
    assert "ワーカー 3" in text
    for row, column, segment, _ in ops:  # nothing is drawn outside the screen
        assert 0 <= row < 34 and column + cells(segment) <= 112
    styles = {style for *_, style in ops}
    assert {"logo0", "logo5", "sel", "key", "warn", "ok"} <= styles


def test_new_item_and_compact_layout():
    inventory = _inventory()
    text = _text(compose(inventory, 1, 0, 112, 34))
    assert "新しい大会を登録します" in text and "CTFd · rCTF" in text
    compact = compose(inventory, 0, 0, 60, 18, message="更新しました")
    assert "◆ METIS" in _text(compact) and LOGO[0] not in _text(compact) and "更新しました" in _text(compact)
    for row, column, segment, _ in compact:
        assert 0 <= row < 18 and column + cells(segment) <= 60


def test_width_helpers():
    assert cells("ab漢字") == 6 and fit("漢字漢字", 5) == "漢字…" and cells(fit("漢字漢字", 5)) == 5
    assert all(cells(line) <= 10 for line in wrap("提出はブラウザのフォームから", 10))
    assert "".join(wrap("提出はブラウザのフォームから", 10)) == "提出はブラウザのフォームから"
