"""后端构建身份。

源码默认值用于本地开发；tag 发布流水线会在 PyInstaller 之前重写本文件，
让版本号真正固化进后端二进制，不能被桌面壳的运行时环境变量伪造。
"""

BACKEND_VERSION = "0.1.0"
BACKEND_BUILD_ID = "development"
