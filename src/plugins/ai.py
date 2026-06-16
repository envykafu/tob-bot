import nonebot

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import to_me

from src.ai_client import chat, config_summary, parse_todo_intent
from src.ai_memory import load_context, save_context
from src.config import settings
from src.db import init_db
from src.time_utils import parse_natural_datetime_prefix
from src.todo_service import add_todo, parse_repeat_interval, parse_todo_from_text


ai_cmd = on_command("ai", priority=30, block=True)
ai_mention = on_message(rule=to_me(), priority=50, block=False)
driver = nonebot.get_driver()

COMMAND_PREFIXES = (
    "/",
    "help",
    "帮助",
    "readme",
    "说明",
    "命令说明",
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
)

INTRO_TEXT = "\n".join(
    [
        "喵～我是在群里帮大家记事和提醒的猫娘助手喵！",
        "我可以帮你记录 todo、课程提醒、黑历史，也可以陪你聊天喵。",
        "你可以这样叫我：",
        "@我 三天后有大作业，每1天提醒我一次",
        "/todo add 明天20:00 英语作业",
        "/课程模板",
        "/添加黑历史",
        "/随机黑历史",
        "更多命令发送 /help 喵。",
    ]
)


@driver.on_startup
async def init_ai_storage() -> None:
    init_db()


def _format_interval(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes % 1440 == 0:
        return f"，每 {minutes // 1440} 天提醒"
    if minutes % 60 == 0:
        return f"，每 {minutes // 60} 小时提醒"
    return f"，每 {minutes} 分钟提醒"


def _looks_like_command(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if text.startswith("/"):
        return True
    return any(text == command or text.startswith(f"{command} ") or text.startswith(f"{command}\n") for command in COMMAND_PREFIXES)


def _reply_bot_message_id(event: GroupMessageEvent, bot: Bot) -> int | None:
    reply = getattr(event, "reply", None)
    if reply is None or reply.sender.user_id is None:
        return None
    if str(reply.sender.user_id) != str(bot.self_id):
        return None
    return int(reply.message_id)


def _split_reply(text: str) -> list[str]:
    size = settings.ai_reply_chunk_size
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.splitlines(keepends=True):
        if len(paragraph) > size:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for index in range(0, len(paragraph), size):
                chunks.append(paragraph[index : index + size].rstrip())
            continue
        if len(current) + len(paragraph) > size:
            chunks.append(current.rstrip())
            current = paragraph
        else:
            current += paragraph
    if current.strip():
        chunks.append(current.rstrip())
    return [chunk for chunk in chunks if chunk]


async def _send_ai_reply(matcher, event: GroupMessageEvent, bot: Bot, reply: str, messages: list[dict[str, str]]) -> None:
    parent_message_id = _reply_bot_message_id(event, bot)
    sent_message_ids: list[int] = []
    chunks = _split_reply(reply)
    for index, chunk in enumerate(chunks, start=1):
        message = chunk if len(chunks) == 1 else f"({index}/{len(chunks)})\n{chunk}"
        result = await matcher.send(message)
        if isinstance(result, dict) and result.get("message_id") is not None:
            sent_message_ids.append(int(result["message_id"]))
    for message_id in sent_message_ids:
        save_context(
            group_id=str(event.group_id),
            user_id=str(event.user_id),
            bot_message_id=message_id,
            parent_bot_message_id=parent_message_id,
            messages=messages,
        )
    await matcher.finish()


@ai_cmd.handle()
async def handle_ai(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    prompt = args.extract_plain_text().strip()
    if not prompt:
        await ai_cmd.finish("用法：/ai 你好")
    if prompt.lower() in {"debug", "配置", "config"}:
        await ai_cmd.finish(config_summary())
    try:
        parent_message_id = _reply_bot_message_id(event, bot)
        reply, messages = await chat(prompt, str(event.user_id), load_context(parent_message_id))
    except Exception as exc:
        await ai_cmd.finish(f"AI 调用失败：{str(exc)[:120]}")
    await _send_ai_reply(ai_cmd, event, bot, reply, messages)


@ai_mention.handle()
async def handle_ai_mention(bot: Bot, event: GroupMessageEvent):
    prompt = event.get_plaintext().strip()
    if not prompt:
        await ai_mention.finish(INTRO_TEXT)
    if _looks_like_command(prompt):
        return
    local_todo = parse_todo_from_text(prompt)
    if local_todo:
        content, due_at = local_todo
        remind_every = parse_repeat_interval(prompt)
        todo_id = add_todo(str(event.group_id), str(event.user_id), content, due_at, remind_every)
        due_text = due_at.strftime("%Y-%m-%d %H:%M") if due_at else "无截止时间"
        await ai_mention.finish(f"已帮你添加 todo #{todo_id}：{content}（{due_text}{_format_interval(remind_every)}）喵")
    intent = await parse_todo_intent(prompt)
    if intent:
        due_at, _rest = parse_natural_datetime_prefix(f"{intent['time_text']} {intent['content']}")
        if due_at:
            remind_every = intent.get("remind_every_minutes")
            if not isinstance(remind_every, int):
                remind_every = None
            todo_id = add_todo(str(event.group_id), str(event.user_id), intent["content"], due_at, remind_every)
            due_text = due_at.strftime("%Y-%m-%d %H:%M")
            await ai_mention.finish(
                f"已帮你添加 todo #{todo_id}：{intent['content']}（{due_text}{_format_interval(remind_every)}）喵"
            )
    try:
        parent_message_id = _reply_bot_message_id(event, bot)
        reply, messages = await chat(prompt, str(event.user_id), load_context(parent_message_id))
    except Exception as exc:
        await ai_mention.finish(f"AI 调用失败：{str(exc)[:120]}")
    await _send_ai_reply(ai_mention, event, bot, reply, messages)
