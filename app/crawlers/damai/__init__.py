from app.crawlers.damai.captcha import DamaiCaptchaSolver
from app.crawlers.damai.crawler import DamaiCrawler
from app.crawlers.damai.fruit_slider import (
    detect_fruit_slider,
    solve_fruit_slider,
    wait_fruit_slider,
)

__all__ = [
    "DamaiCrawler",
    "DamaiCaptchaSolver",
    "detect_fruit_slider",
    "solve_fruit_slider",
    "wait_fruit_slider",
]
