"""全局 APScheduler 单例（P8.2）。

main.py lifespan 注册任务，/api/system/health-report 读取运行状态，
必须共享同一实例（原先为 main 模块私有变量，健康自检无法触达）。
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(timezone="UTC")
