import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from src.config import settings


nonebot.init(
    host=settings.host,
    port=settings.port,
    superusers=set(settings.superusers),
    nickname=set(settings.nickname),
    command_start=set(settings.command_start),
)

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()
