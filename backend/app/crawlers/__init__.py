from app.crawlers.base import BaseCrawler
from app.crawlers.damai import DamaiCaptchaSolver, DamaiCrawler
from app.crawlers.maoyan import MaoyanCaptchaSolver, MaoyanCrawler
from app.crawlers.registry import get_crawler, list_crawlers

__all__ = [
    "BaseCrawler",
    "DamaiCrawler",
    "DamaiCaptchaSolver",
    "MaoyanCrawler",
    "MaoyanCaptchaSolver",
    "get_crawler",
    "list_crawlers",
]
