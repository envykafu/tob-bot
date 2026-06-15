import base64
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.typing import T_State


help_cmd = on_command("help", aliases={"帮助"}, priority=10, block=True)
HELP_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "help_menu.png"
HELP_FALLBACK = "\n".join(
    [
        "常用命令：",
        "/todo add 明天20:00 写作业",
        "/重要日程 add 2026-06-20 考试",
        "/课程模板；/导入课程表；/查看课程",
        "/添加黑历史；/随机黑历史；/黑历史 list",
        "/扔漂流瓶；/捡漂流瓶",
        "/ai 你好；@tobbot 你好",
    ]
)


def _help_message():
    if not HELP_IMAGE_PATH.exists():
        return HELP_FALLBACK
    encoded = base64.b64encode(HELP_IMAGE_PATH.read_bytes()).decode("ascii")
    return MessageSegment.text("常用命令见图；详细说明见 README。") + MessageSegment.image(f"base64://{encoded}")


@help_cmd.handle()
async def handle_help(event: MessageEvent, state: T_State):
    await help_cmd.finish(_help_message())
