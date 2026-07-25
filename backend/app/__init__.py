"""daxicrawler 本地 Web 服务层（FastAPI）。

在本机 localhost 运行，供前端页面查询清洗后的 Show 数据，并支持 CSV / Excel 导出。
数据来源为固定本地 SQLite 库（默认 data/daxi.sqlite3）。
"""

__version__ = "0.1.0"
