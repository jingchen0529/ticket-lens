from app.utils.show_visibility import summarize_ledger_visibility


def test_summarize_ledger_visibility_reconciles_hidden_categories():
    visible, hidden, breakdown = summarize_ledger_visibility(
        ["话剧歌剧"] * 141 + ["展览休闲"] * 40 + ["体育"] * 2
    )

    assert visible == 141
    assert hidden == 42
    assert breakdown == {"展览休闲": 40, "体育": 2}
