"""命令行入口。"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from app import __version__
from app.core.config import load_config
from app.models import CrawlJob, SourcePlatform
from app.services.crawl import run_crawl
from app.utils.logging import setup_logging

app = typer.Typer(
    name="daxi",
    help="大麦 / 猫眼 / 秀动演出数据采集工具",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _parse_sources(sources: str) -> list[SourcePlatform]:
    parts = [p.strip().lower() for p in sources.split(",") if p.strip()]
    if not parts or "all" in parts:
        return [SourcePlatform.DAMAI, SourcePlatform.MAOYAN, SourcePlatform.SHOWSTART]
    out: list[SourcePlatform] = []
    for p in parts:
        if p in ("damai", "大麦"):
            out.append(SourcePlatform.DAMAI)
        elif p in ("maoyan", "猫眼"):
            out.append(SourcePlatform.MAOYAN)
        elif p in ("showstart", "秀动"):
            out.append(SourcePlatform.SHOWSTART)
        else:
            raise typer.BadParameter(f"未知源: {p}，可选 damai,maoyan,showstart,all")
    return out


@app.command("version")
def version() -> None:
    """显示版本。"""
    console.print(f"daxi {__version__}")


@app.command("browser-check")
def browser_check(
    headed: bool = typer.Option(True, "--headed/--headless", help="默认有头，验证窗口能弹出"),
    url: str = typer.Option("https://www.baidu.com", "--url", help="打开的测试页"),
    wait: int = typer.Option(4, "--wait", help="停留秒数，便于肉眼确认窗口"),
) -> None:
    """打包验证专用：启动 Chromium 打开一个页面，确认有头窗口能弹出。"""
    import os

    async def _run() -> int:
        from playwright.async_api import async_playwright

        from app.core.paths import setup_browser_env

        # 与生产采集一致：打包后自动指向随包 Chromium
        setup_browser_env()

        console.print(
            f"[bold]browser-check[/bold] headed={headed} "
            f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '(default)')}"
        )
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            title = await page.title()
            console.print(f"[green]OK[/green] launched, title={title!r}")
            await page.wait_for_timeout(wait * 1000)
            await browser.close()
            return 0

    code = asyncio.run(_run())
    raise typer.Exit(code=code)


@app.command("crawl")
def crawl(
    sources: str = typer.Option(
        "all",
        "--sources",
        "-s",
        help="数据源：damai,maoyan,showstart,all",
    ),
    city: Optional[list[str]] = typer.Option(
        None,
        "--city",
        "-c",
        help="城市，可重复。不传则用配置文件",
    ),
    keyword: Optional[list[str]] = typer.Option(
        None,
        "--keyword",
        "-k",
        help="搜索关键词，可重复。不传则抓分类/列表",
    ),
    category: str = typer.Option(
        "",
        "--category",
        help="单平台分类（如大麦话剧歌剧、猫眼话剧音乐剧、秀动爵士）；不传则抓全部分类",
    ),
    max_pages: Optional[int] = typer.Option(
        None,
        "--max-pages",
        "-p",
        help="每个城市/关键词最多页数；0=全部（跟列表 totalPage）",
    ),
    config_path: str = typer.Option(
        "configs/default.yaml",
        "--config",
        help="配置文件路径",
    ),
    headed: bool = typer.Option(
        False,
        "--headed",
        help="有头模式（遇到验证码可手动处理）",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="强制无头（默认跟配置）",
    ),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="存储：json 或 sqlite",
    ),
    captcha_provider: Optional[str] = typer.Option(
        None,
        "--captcha-provider",
        help="验证码：local_slider / capsolver / twocaptcha",
    ),
    no_auto_captcha: bool = typer.Option(
        False,
        "--no-auto-captcha",
        help="关闭自动过验证（仅人工）",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="调试日志"),
) -> None:
    """执行一次采集，输出统一 Show 数据。"""
    setup_logging(verbose, console)
    cfg = load_config(config_path)

    if headed:
        cfg.browser.headless = False
    elif headless:
        cfg.browser.headless = True

    if backend:
        cfg.storage.backend = backend
    if captcha_provider:
        cfg.captcha.provider = captcha_provider
    if no_auto_captcha:
        cfg.captcha.auto = False

    cities = list(city) if city else list(cfg.crawl.cities)
    keywords = list(keyword) if keyword else list(cfg.crawl.keywords)
    # CLI：显式 --max-pages 优先；0=全量；不传则跟配置文件
    if max_pages is not None:
        pages = max(0, int(max_pages))
    else:
        pages = int(cfg.crawl.max_pages)

    job = CrawlJob(
        sources=_parse_sources(sources),
        cities=cities,
        keywords=keywords,
        category=category.strip(),
        max_pages=pages,
    )

    pages_label = "全部" if pages <= 0 else str(pages)
    console.print(
        f"[bold]daxi crawl[/bold] sources={[s.value for s in job.sources]} "
        f"cities={job.cities} category={job.category or '全部'} "
        f"keywords={job.keywords or '—'} pages={pages_label} "
        f"headless={cfg.browser.headless}"
    )

    result = asyncio.run(run_crawl(job, cfg))

    table = Table(title="Crawl Result")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("raw_count", str(result.raw_count))
    table.add_row("show_count", str(result.show_count))
    table.add_row("ledger_visible_count", str(result.ledger_visible_count or 0))
    table.add_row("ledger_hidden_count", str(result.ledger_hidden_count or 0))
    table.add_row("ledger_hidden_by_category", str(result.ledger_hidden_by_category))
    table.add_row("by_source", str(result.by_source))
    table.add_row("errors", str(len(result.errors)))
    table.add_row("output", result.output_path)
    console.print(table)

    if result.errors:
        console.print("[yellow]errors:[/yellow]")
        for e in result.errors:
            console.print(f"  - {e}")

    if result.show_count == 0 and result.errors:
        raise typer.Exit(code=1)


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址；默认仅本机"),
    port: int = typer.Option(8000, "--port", help="端口"),
    reload: bool = typer.Option(False, "--reload", help="改代码自动重启（开发用）"),
    supervised: bool = typer.Option(
        False,
        "--supervised",
        help="由桌面壳监督生命周期（内部选项）",
        hidden=True,
    ),
) -> None:
    """启动本地 API 服务（前端从这里查询/导出数据）。"""
    import uvicorn

    # 服务模式下根日志也要有落盘通道：Windows 打包版控制台不可见，
    # 任务失败的真实堆栈只进 server.log 文件。
    setup_logging(verbose=False, console=console)
    if host not in ("127.0.0.1", "localhost"):
        console.print(
            f"[yellow]注意：host={host} 会对外暴露服务，本地应用建议保持 127.0.0.1[/yellow]"
        )
    console.print(f"[bold]daxi serve[/bold] http://{host}:{port}  (docs: /docs)")

    if supervised and reload:
        raise typer.BadParameter("--supervised 不能与 --reload 同时使用")

    # PyInstaller 冻结后无法用 "app.main:app" 字符串导入（uvicorn 会重新按模块路径
    # import，冻结环境里失效）。此时直接传入 app 对象。reload 依赖字符串路径与子进程，
    # 打包环境用不到，仅开发时走字符串分支。
    # log_config=None：不覆盖我们刚配好的根日志（文件+控制台），uvicorn 日志冒泡到 root。
    if supervised:
        from app.main import app as asgi_app
        from app.utils.process_supervisor import start_parent_pipe_watchdog

        config = uvicorn.Config(asgi_app, host=host, port=port, log_config=None)
        server = uvicorn.Server(config)
        start_parent_pipe_watchdog(server)
        server.run()
    elif getattr(sys, "frozen", False):
        from app.main import app as asgi_app

        uvicorn.run(asgi_app, host=host, port=port, log_config=None)
    else:
        uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_config=None)


@app.command("show-config")
def show_config(
    config_path: str = typer.Option("configs/default.yaml", "--config"),
) -> None:
    """打印当前配置。"""
    cfg = load_config(config_path)
    console.print_json(cfg.model_dump_json(indent=2))


@app.command("captcha-test")
def captcha_test(
    source: str = typer.Option("damai", "--source", "-s", help="damai | maoyan"),
    config_path: str = typer.Option("configs/default.yaml", "--config"),
    headed: bool = typer.Option(True, "--headed/--headless", help="默认有头，便于观察"),
    verbose: bool = typer.Option(True, "--verbose/--quiet", "-v"),
) -> None:
    """只测验证码自动过验证（打开对应站点搜索页触发风控）。"""
    setup_logging(verbose, console)
    cfg = load_config(config_path)
    cfg.browser.headless = not headed

    async def _run() -> int:
        from app.browser.session import browser_session
        from app.crawlers.registry import get_crawler
        from app.models import SourcePlatform

        source_key = source.strip().lower()
        if source_key in ("damai", "大麦"):
            src = SourcePlatform.DAMAI
        elif source_key in ("maoyan", "猫眼"):
            src = SourcePlatform.MAOYAN
        else:
            raise typer.BadParameter(
                "captcha-test 仅支持 damai|maoyan（showstart 为纯 HTTP 无验证码）"
            )
        platform_captcha = cfg.captcha_for(src.value)
        run_cfg = cfg.model_copy(deep=True)
        run_cfg.captcha = platform_captcha

        url = (
            "https://search.damai.cn/search.htm?ctl=%E6%BC%94%E5%94%B1%E4%BC%9A&cty=%E5%8C%97%E4%BA%AC&order=1"
            if src == SourcePlatform.DAMAI
            else "https://show.maoyan.com/qqw#/list?cityName=%E5%8C%97%E4%BA%AC"
        )

        async with browser_session(run_cfg.browser, run_cfg.captcha, platform=src.value) as session:
            crawler = get_crawler(src, session, run_cfg)
            async with session.page() as page:
                console.print(f"[bold]captcha-test[/bold] {src.value} → {url}")
                try:
                    await crawler.goto(page, url, wait_until="domcontentloaded")
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[yellow]goto/captcha: {exc}[/yellow]")
                await page.wait_for_timeout(2000)
                # 再触发一次 ajax 风控（多刷几页提高命中）。
                # 注意：风控触发常导致页面导航到 punish 页，会让 evaluate 的
                # 执行上下文被销毁并抛异常——这恰恰说明「已触发」，不能当失败退出。
                if src == SourcePlatform.DAMAI:
                    for i in range(1, 8):
                        if await crawler.captcha.detect(page) is not None:
                            break
                        try:
                            await page.evaluate(
                                "(n) => { fetch('/searchajax.html?keyword=a&cty=%E5%8C%97%E4%BA%AC"
                                "&pageSize=30&currPage=' + n + '&order=1',"
                                "{credentials:'include'}).catch(()=>{}); }",
                                i + 10,
                            )
                        except Exception as exc:  # noqa: BLE001
                            # 上下文被导航销毁 = 风控已触发
                            console.print(f"[dim]trigger navigated (likely punish): {exc}[/dim]")
                        await page.wait_for_timeout(1500)

                # 统一走完整链路：detect → ensure_cleared（会调冰拓拿距离并自动拖滑块）
                ch = await crawler.captcha.detect(page)
                if ch is None:
                    console.print("[yellow]未检测到验证码/风控（可能本次未触发）[/yellow]")
                    return 0
                console.print(f"[bold]detected:[/bold] {ch.kind.value} {ch.reason}")
                result = await crawler.captcha.ensure_cleared(page)
                console.print(
                    f"[bold]result:[/bold] ok={result.ok} method={result.method} "
                    f"attempts={result.attempts} msg={result.message}"
                )
                return 0 if result.ok else 1

    code = asyncio.run(_run())
    raise typer.Exit(code=code)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
