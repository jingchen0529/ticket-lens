"""导出模板规范字段测试。"""

from app.services.export import _norm_title


def test_norm_title_keeps_all_bracketed_titles():
    """原名称里有多个书名号剧目时全部保留（曲苑杂坛多剧目连演场景）。"""
    assert (
        _norm_title("《天空之城》《龙猫》《悬崖上的金鱼姬》宫崎骏经典动漫视听音乐会")
        == "《天空之城》《龙猫》《悬崖上的金鱼姬》"
    )


def test_norm_title_single_bracket():
    assert _norm_title("《茶馆》老舍经典话剧") == "《茶馆》"


def test_norm_title_brackets_with_gap_keep_order():
    assert _norm_title("《A》经典名段《B》专场") == "《A》《B》"


def test_norm_title_without_brackets_stays_empty():
    """无书名号留空待人工规范（原有行为）。"""
    assert _norm_title("某某音乐节") == ""
    assert _norm_title("") == ""