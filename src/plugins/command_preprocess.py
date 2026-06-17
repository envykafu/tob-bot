from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.message import event_preprocessor


DIRECT_COMMANDS = {
    "help",
    "帮助",
    "readme",
    "说明",
    "命令说明",
    "status",
    "状态",
    "todo",
    "course",
    "课表",
    "添加课程",
    "删除课程",
    "取消课程",
    "移动课程",
    "查看课程",
    "课程表",
    "课程模板",
    "导入课程表",
    "black",
    "黑历史",
    "添加黑历史",
    "随机黑历史",
    "删除黑历史",
    "bottle",
    "漂流瓶",
    "扔漂流瓶",
    "丢漂流瓶",
    "投漂流瓶",
    "扔瓶子",
    "丢瓶子",
    "捡漂流瓶",
    "捞漂流瓶",
    "拾漂流瓶",
    "捡瓶子",
    "捞瓶子",
    "删除漂流瓶",
    "删漂流瓶",
    "schedule",
    "重要日程",
    "添加重要日程",
    "查看重要日程",
    "删除重要日程",
    "ai",
}


def _strip_leading_self_at(message: Message, self_id: str) -> tuple[Message, bool]:
    segments = list(message)
    changed = False
    while segments:
        segment = segments[0]
        if segment.type == "at" and str(segment.data.get("qq")) == self_id:
            segments.pop(0)
            changed = True
            continue
        if segment.type == "text":
            text = str(segment.data.get("text", ""))
            stripped = text.lstrip()
            if stripped != text:
                changed = True
            if not stripped:
                segments.pop(0)
                continue
            segments[0] = MessageSegment.text(stripped)
        break
    return Message(segments), changed


def _with_command_start(message: Message) -> Message:
    text = message.extract_plain_text().strip()
    if not text or text.startswith("/"):
        return message
    for command in sorted(DIRECT_COMMANDS, key=len, reverse=True):
        if text == command or text.startswith(f"{command} ") or text.startswith(f"{command}\n"):
            segments = list(message)
            for index, segment in enumerate(segments):
                if segment.type != "text":
                    continue
                segment_text = str(segment.data.get("text", ""))
                stripped = segment_text.lstrip()
                if not stripped:
                    continue
                segments[index] = MessageSegment.text(f"/{stripped}")
                return Message(segments)
    return message


@event_preprocessor
async def normalize_at_command(bot: Bot, event: GroupMessageEvent):
    message, changed = _strip_leading_self_at(event.get_message(), str(bot.self_id))
    if not changed:
        return
    message = _with_command_start(message)
    event.message = message
    event.raw_message = str(message)
