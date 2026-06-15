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


async def _save_black_history(event: GroupMessageEvent, message: Message):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    urls = _image_urls(message)
    text = _plain_text(message)
    if not urls and not text:
        return "没有收到图片或文字，已取消添加。"

    settings.black_history_dir.mkdir(parents=True, exist_ok=True)
    downloaded_paths: list[Path] = []
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
        return await _save_black_history(event, message)

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
            return item.content
        path = Path(item.file_path)
        if not path.exists():
            return "抽到的图片文件不存在，可能被手动删除了。"
        try:
            encoded = read_image_base64(path)
        except Exception as exc:
            return f"抽到的图片无法发送：{exc}"
        return MessageSegment.image(f"base64://{encoded}")

    if action in {"delete", "删除"}:
        if not _is_admin(user_id):
            return "只有 bot 管理员可以删除黑历史。"
        target = payload.strip()
        if not target.isdigit():
            return "用法：/删除黑历史 图片ID"
        with session_scope() as session:
            item = session.scalar(
                select(BlackHistory).where(BlackHistory.id == int(target), BlackHistory.group_id == group_id)
            )
            if item is None:
                return "没有找到这条黑历史。"
            path = Path(item.file_path)
            session.delete(item)
        if str(path) != "." and path.exists():
            os.remove(path)
        return f"已删除黑历史 #{target}。"

    return "用法：/添加黑历史，按提示发送图片或文字；/随机黑历史；/删除黑历史 图片ID（管理员）"


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
