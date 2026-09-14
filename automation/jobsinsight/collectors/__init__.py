"""数据采集器。

内置三种来源类型：

* ``fixture``   —— 读取本地 JSON（默认，离线可用）
* ``json_api``  —— 任意 JSON 接口，字段通过配置映射
* ``html_llm``  —— 抓取网页并让 LLM 抽取结构化岗位
* ``browser``   —— 可选 Playwright，使用用户授权的持久化登录会话

自定义来源可以通过 :func:`register_collector` 注册。
"""

from . import browser, fixture, html_llm, json_api  # noqa: F401 - imported for registration
from .base import (
    Collector,
    CollectorContext,
    CollectorError,
    available_collectors,
    build_collector,
    register_collector,
)

__all__ = [
    "Collector",
    "CollectorContext",
    "CollectorError",
    "available_collectors",
    "build_collector",
    "register_collector",
]
