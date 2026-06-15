import secrets
import os
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.typing import T_State
from sqlalchemy import delete, func, select

from src.config import settings
from src.db import BlackHistory, init_db, session_scope
from src.image_utils import download_image, read_image_base64


black_cmd = on_command("black", aliases={"黑历史"}, priority=20, block=True)
add_black_cmd = on_command("添加黑历史", priority=20, block=True)
random_black_cmd = on_command("随机黑历史", priority=20, block=True)
delete_black_cmd = on_command("删除黑历史", priority=20, block=True)


def _image_urls(message: Message) -> list[str]:
    urls = []
    for segment in message:
        if segment.type != "image":
            continue
        url = segment.data.get("url") or segment.data.get("file")
        if url:
            urls.append(str(url))
    return urls


def _plain_text(message: Message) -> str:
    return message.extract_plain_text().strip()


def _is_admin(user_id: str) -> bool:
    return user_id in set(settings.superusers)


def _is_group_manager(event: GroupMessageEvent) -> bool:
    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", "") if sender is not None else ""
    return role in {"owner", "admin"}


def _can_delete_black_history(event: GroupMessageEvent, item: BlackHistory) -> bool:
    return _is_admin(str(event.user_id)) or _is_group_manager(event) or item.user_id == str(event.user_id)


def _format_black_history_item(item: BlackHistory) -> str:
    if item.content_type == "text":
        preview = item.content.replace("\n", " ").strip()
        if len(preview) > 30:
            preview = preview[:30] + "..."
        return f"#{item.id} 文本 {preview}"
    return f"#{item.id} 图片"


async def _save_black_history(event: GroupMessageEvent, message: Message, text_override: str | None = None):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    urls = _image_urls(message)
    text = (text_override if text_override is not None else _plain_text(message)).strip()
    if not urls and not text:
        return "没有收到图片或文字，已取消添加。"

    incoming_count = len(urls) + (1 if text else 0)
    with session_scope() as session:
        group_count = session.scalar(
            select(func.count()).select_from(BlackHistory).where(BlackHistory.group_id == group_id)
        ) or 0
        user_count = session.scalar(
            select(func.count())
            .select_from(BlackHistory)
            .where(BlackHistory.group_id == group_id, BlackHistory.user_id == user_id)
        ) or 0
    if int(group_count) + incoming_count > settings.black_history_max_per_group:
        return f"本群黑历史已达到上限 {settings.black_history_max_per_group} 条，请先删除旧记录。"
    if int(user_count) + incoming_count > settings.black_history_max_per_user:
        return f"你的黑历史已达到上限 {settings.black_history_max_per_user} 条，请先删除旧记录。"

    downloaded_paths: list[Path] = []
    if urls:
        settings.black_history_dir.mkdir(parents=True, exist_ok=True)
        for url in urls:
            filename = f"{group_id}_{user_id}_{secrets.token_hex(8)}.jpg"
            path = settings.black_history_dir / filename
            try:
                await download_image(url, path)
            except Exception as exc:
                for downloaded_path in downloaded_paths:
                    downloaded_path.unlink(missing_ok=True)
                return f"图片保存失败：{exc}"
            downloaded_paths.append(path)

    saved = 0
    try:
        with session_scope() as session:
            for path in downloaded_paths:
                session.add(
                    BlackHistory(
                        group_id=group_id,
                        user_id=user_id,
                        content_type="image",
                        content="",
                        file_path=str(path),
                    )
                )
                saved += 1
            if text:
                session.add(
                    BlackHistory(
                        group_id=group_id,
                        user_id=user_id,
                        content_type="text",
                        content=text,
                        file_path="",
                    )
                )
                saved += 1
    except Exception as exc:
        for downloaded_path in downloaded_paths:
            downloaded_path.unlink(missing_ok=True)
        return f"黑历史保存失败：{exc}"
    return f"已保存 {saved} 条黑历史。"


async def _handle_black(event: GroupMessageEvent, raw: str, message: Message):
    init_db()
    action, _, payload = raw.partition(" ")
    action = action.lower()
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    if action in {"add", "upload", "上传"}:
        return await _save_black_history(event, message, payload.strip())

    if action in {"random", "随机"}:
        with session_scope() as session:
            total = session.scalar(select(func.count()).select_from(BlackHistory).where(BlackHistory.group_id == group_id))
            if not total:
                return "这个群还没有黑历史。"
            offset = secrets.randbelow(int(total))
            item = session.scalar(
                select(BlackHistory).where(BlackHistory.group_id == group_id).order_by(BlackHistory.id).offset(offset).limit(1)
            )
        if item is None:
            return "这个群还没有黑历史。"
        if item.content_type == "text":
            return f"黑历史 #{item.id}：{item.content}"
        path = Path(item.file_path)
        if not path.exists():
            return f"抽到的图片文件不存在（#{item.id}），可能被手动删除了。"
        try:
            encoded = read_image_base64(path)
        except Exception as exc:
            return f"抽到的图片 #{item.id} 无法发送：{exc}"
        return MessageSegment.text(f"黑历史 #{item.id}：\n") + MessageSegment.image(f"base64://{encoded}")

    if action in {"list", "列表"}:
        with session_scope() as session:
            items = session.scalars(
                select(BlackHistory)
                .where(BlackHistory.group_id == group_id)
                .order_by(BlackHistory.id.desc())
                .limit(10)
            ).all()
        if not items:
            return "这个群还没有黑历史。"
        lines = ["最近 10 条黑历史："]
        lines.extend(_format_black_history_item(item) for item in items)
        return "\n".join(lines)

    if action in {"delete", "删除"}:
        target = payload.strip()
        if not target.isdigit():
            return "用法：/删除黑历史 ID"
        with session_scope() as session:
            item = session.scalar(
                select(BlackHistory).where(BlackHistory.id == int(target), BlackHistory.group_id == group_id)
            )
            if item is None:
                return "没有找到这条黑历史。"
            if not _can_delete_black_history(event, item):
                return "只有记录创建者、群管理员或 bot 管理员可以删除黑历史。"
            path = Path(item.file_path)
            session.delete(item)
        if str(path) != "." and path.exists():
            os.remove(path)
        return f"已删除黑历史 #{target}。"

    return "用法：/添加黑历史，按提示发送图片或文字；/随机黑历史；/黑历史 list；/删除黑历史 ID"


@black_cmd.handle()
async def handle_black(event: GroupMessageEvent, state: T_State, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if raw.lower() in {"add", "upload"} and not _image_urls(args):
        await black_cmd.send("请发送黑历史")
        state["waiting_black"] = True
        return
    await black_cmd.finish(await _handle_black(event, raw, args))


@black_cmd.got("black_content")
async def handle_black_content(event: GroupMessageEvent, state: T_State):
    if not state.get("waiting_black"):
        return
    await black_cmd.finish(await _save_black_history(event, event.get_message()))


@add_black_cmd.handle()
async def handle_add_black_first(event: GroupMessageEvent, state: T_State, args: Message = CommandArg()):
    if _image_urls(args) or _plain_text(args):
        await add_black_cmd.finish(await _save_black_history(event, args))
    await add_black_cmd.send("请发送黑历史")


@add_black_cmd.got("black_content")
async def handle_add_black_content(event: GroupMessageEvent, state: T_State):
    await add_black_cmd.finish(await _save_black_history(event, event.get_message()))


@random_black_cmd.handle()
async def handle_random_black(event: GroupMessageEvent):
    await random_black_cmd.finish(await _handle_black(event, "random", Message()))


@delete_black_cmd.handle()
async def handle_delete_black(event: GroupMessageEvent, args: Message = CommandArg()):
    await delete_black_cmd.finish(await _handle_black(event, f"delete {args.extract_plain_text().strip()}", args))
