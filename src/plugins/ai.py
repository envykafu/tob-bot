from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import to_me

from src.ai_client import chat, config_summary, parse_todo_intent
from src.time_utils import parse_natural_datetime_prefix
from src.todo_service import add_todo, parse_repeat_interval, parse_todo_from_text


ai_cmd = on_command("ai", priority=30, block=True)
ai_mention = on_message(rule=to_me(), priority=50, block=False)

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


@ai_cmd.handle()
async def handle_ai(event: GroupMessageEvent, args: Message = CommandArg()):
    prompt = args.extract_plain_text().strip()
    if not prompt:
        await ai_cmd.finish("用法：/ai 你好")
    if prompt.lower() in {"debug", "配置", "config"}:
        await ai_cmd.finish(config_summary())
    try:
        reply = await chat(prompt, str(event.user_id))
    except Exception as exc:
        await ai_cmd.finish(f"AI 调用失败：{str(exc)[:120]}")
    await ai_cmd.finish(reply)


@ai_mention.handle()
async def handle_ai_mention(event: GroupMessageEvent):
    prompt = event.get_plaintext().strip()
    if not prompt:
        await ai_mention.finish(INTRO_TEXT)
    local_todo = parse_todo_from_text(prompt)
    if local_todo:
        content, due_at = local_todo
        remind_every = parse_repeat_interval(prompt)
        todo_id = add_todo(str(event.group_id), str(event.user_id), content, due_at, remind_every)
        due_text = due_at.strftime("%Y-%m-%d %H:%M") if due_at else "无截止时间"
        await ai_mention.finish(f"已帮你添加 todo #{todo_id}：{content}（{due_text}）喵")
    intent = await parse_todo_intent(prompt)
    if intent:
        due_at, _rest = parse_natural_datetime_prefix(f"{intent['time_text']} {intent['content']}")
        if due_at:
            remind_every = intent.get("remind_every_minutes")
            if not isinstance(remind_every, int):
                remind_every = None
            todo_id = add_todo(str(event.group_id), str(event.user_id), intent["content"], due_at, remind_every)
            due_text = due_at.strftime("%Y-%m-%d %H:%M")
            await ai_mention.finish(f"已帮你添加 todo #{todo_id}：{intent['content']}（{due_text}）喵")
    try:
        reply = await chat(prompt, str(event.user_id))
    except Exception as exc:
        await ai_mention.finish(f"AI 调用失败：{str(exc)[:120]}")
    await ai_mention.finish(reply)
