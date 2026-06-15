from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.params import CommandArg
from nonebot.typing import T_State


help_cmd = on_command("help", aliases={"帮助"}, priority=10, block=True)


@help_cmd.handle()
async def handle_help(event: MessageEvent, state: T_State):
    await help_cmd.finish(
        "\n".join(
            [
                "命令说明：",
                "",
                "todo：个人待办，只显示和提醒你自己的任务。",
                "/todo add 三天 大作业 每 1 天",
                "/todo add 明天 09:00-11:00 大作业：设置开始和结束时间。",
                "/todo add 截止 明天20:00 大作业：只设置截止时间。",
                "参数：时间可写 2026/6/15、2026-06-15 20:00、明天、三天；不写具体时间默认中午 12:00。",
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
                "/删除黑历史 图片ID：删除黑历史，仅 bot 管理员可用。",
                "",
                "漂流瓶：所有群共享。",
                "/扔漂流瓶、/丢漂流瓶、/扔瓶子：bot 提示后，发送文字或图片。",
                "/捡漂流瓶、/捞漂流瓶、/捡瓶子：从所有群共享瓶子里随机捡一个。",
                "/删除漂流瓶 ID：删除漂流瓶，仅 bot 管理员可用。",
                "",
                "AI：/ai 你好，或 @bot 闲聊；@bot + 命令会优先执行命令。",
            ]
        )
    )
