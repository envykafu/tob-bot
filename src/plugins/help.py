import base64
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.typing import T_State


help_cmd = on_command("help", aliases={"帮助"}, priority=10, block=True)
readme_cmd = on_command("readme", aliases={"说明", "命令说明"}, priority=10, block=True)
HELP_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "help_menu.png"
README_HELP_TEXT = "\n".join(
    [
        "命令说明：",
        "",
        "todo：个人待办，只显示和提醒你自己的任务。",
        "/todo add 三天 大作业 每 1 天",
        "/todo 晚上六点检查卫生：直接按自然语言添加，默认提前 15 分钟提醒。",
        "/todo add 明天 09:00-11:00 大作业：设置开始和结束时间。",
        "/todo add 截止 明天20:00 大作业：只设置截止时间。",
        "参数：时间可写 2026/6/15、2026-06-15 20:00、明天、三天、10分钟后、半小时后；不写具体时间默认中午 12:00。",
        "重复提醒：每 1 天、每 3 天、每 60 分钟均可；有截止时间时，截止前一天每 2 小时提醒一次。",
        "/todo list：查看未完成任务。",
        "/todo done 1 或 /todo done 写报告：按 ID 或名称完成。",
        "/todo delete 1 或 /todo delete 写报告：按 ID 或名称删除。",
        "",
        "重要日程：每天早上 08:00 倒计时提醒。",
        "/重要日程 add 2026-06-20 考试：添加重要日程。",
        "/重要日程 list：查看重要日程。",
        "/重要日程 delete 1：删除重要日程。",
        "",
        "course：个人课程表，提醒固定提前 15 分钟。",
        "/课程模板：查看 CSV 表头。",
        "/导入课程表 粘贴CSV：导入课程，必须包含 start_date/end_date。",
        "weeks 支持：1-16、1,3,5、单周、双周、1-16单周、2-16双周。",
        "/查看课程：查看课程。",
        "/删除课程 2026-10-01 all：取消某天全部课程。",
        "/删除课程 2026-10-01 课程ID或课程名：取消某天单节课。",
        "/添加课程 2026-10-08 08:00-09:40 课程名 地点：临时加课。",
        "/移动课程 课程ID 原日期 新日期 10:00-11:40 地点：调课。",
        "",
        "black：群黑历史图片。",
        "/添加黑历史：bot 提示后，发送图片或文字保存到本地。",
        "/随机黑历史：随机发送一张本群黑历史。",
        "/删除黑历史 图片ID：删除黑历史，允许记录创建者、群管理员或 bot 管理员操作。",
        "",
        "漂流瓶：所有群共享。",
        "/扔漂流瓶：bot 提示后，发送文字或图片。",
        "/捡漂流瓶：从所有群共享瓶子里随机捡一个。",
        "",
        "AI：/ai 你好，或 @bot 闲聊。需要在 .env 配 AI_API_KEY。",
        "管理员：/status 查看 bot 运行状态。",
    ]
)
HELP_FALLBACK = "\n".join(
    [
        "常用命令：",
        "/todo add 明天20:00 写作业",
        "/重要日程 add 2026-06-20 考试",
        "/课程模板；/导入课程表；/查看课程",
        "/添加黑历史；/随机黑历史；/黑历史 list",
        "/扔漂流瓶；/捡漂流瓶",
        "/ai 你好；@tobbot 你好",
        "/status 管理员查看 bot 状态",
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


@readme_cmd.handle()
async def handle_readme(event: MessageEvent, state: T_State):
    await readme_cmd.finish(README_HELP_TEXT)
