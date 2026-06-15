import base64
import os
import secrets
from pathlib import Path

import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.typing import T_State
from sqlalchemy import func, select

from src.config import settings
from src.db import DriftBottle, init_db, session_scope


BOTTLE_THROW_ALIASES = {"丢漂流瓶", "投漂流瓶", "扔瓶子", "丢瓶子"}
BOTTLE_PICK_ALIASES = {"捞漂流瓶", "拾漂流瓶", "捡瓶子", "捞瓶子"}
BOTTLE_DELETE_ALIASES = {"删漂流瓶"}

bottle_cmd = on_command("bottle", aliases={"漂流瓶"}, priority=20, block=True)
throw_bottle_cmd = on_command("扔漂流瓶", aliases=BOTTLE_THROW_ALIASES, priority=20, block=True)
pick_bottle_cmd = on_command("捡漂流瓶", aliases=BOTTLE_PICK_ALIASES, priority=20, block=True)
delete_bottle_cmd = on_command("删除漂流瓶", aliases=BOTTLE_DELETE_ALIASES, priority=20, block=True)


def _bottle_dir() -> Path:
    path = settings.db_path.parent / "drift_bottles"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


async def _download_image(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    dest.write_bytes(response.content)


def _is_admin(user_id: str) -> bool:
    return user_id in set(settings.superusers)


async def _save_bottle(event: GroupMessageEvent, message: Message, text_override: str | None = None):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    urls = _image_urls(message)
    text = _plain_text(message) if text_override is None else text_override.strip()
    if not urls and not text:
        return "没有收到漂流瓶内容，已取消。"

    saved = 0
    with session_scope() as session:
        for url in urls:
            filename = f"{group_id}_{user_id}_{secrets.token_hex(8)}.jpg"
            path = _bottle_dir() / filename
            try:
                await _download_image(url, path)
            except Exception as exc:
                return f"漂流瓶图片保存失败：{exc}"
            session.add(
                DriftBottle(
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
                DriftBottle(
                    group_id=group_id,
                    user_id=user_id,
                    content_type="text",
                    content=text,
                    file_path="",
                )
            )
            saved += 1
    return f"已扔出 {saved} 个漂流瓶。"


def _format_bottle(item: DriftBottle):
    if item.content_type == "text":
        item.picked_count += 1
        return item.content
    path = Path(item.file_path)
    if not path.exists():
        return "捡到的漂流瓶图片文件不存在，可能被手动删除了。"
    item.picked_count += 1
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return MessageSegment.image(f"base64://{encoded}")


async def _pick_bottle():
    init_db()
    with session_scope() as session:
        total = session.scalar(select(func.count()).select_from(DriftBottle))
        if not total:
            return "海里还没有漂流瓶。"
        offset = secrets.randbelow(int(total))
        item = session.scalar(select(DriftBottle).order_by(DriftBottle.id).offset(offset).limit(1))
        if item is None:
            return "海里还没有漂流瓶。"
        return _format_bottle(item)


async def _handle_bottle(event: GroupMessageEvent, raw: str, message: Message):
    init_db()
    action, _, payload = raw.partition(" ")
    action = action.lower()
    user_id = str(event.user_id)
    if action in {"throw", "toss", "扔", "丢", "投", "add", "添加"}:
        return await _save_bottle(event, message, payload)
    if action in {"pick", "捡", "捞", "拾", "random", "随机"}:
        return await _pick_bottle()
    if action in {"delete", "删除", "删"}:
        if not _is_admin(user_id):
            return "只有 bot 管理员可以删除漂流瓶。"
        target = payload.strip()
        if not target.isdigit():
            return "用法：/删除漂流瓶 漂流瓶ID"
        with session_scope() as session:
            item = session.scalar(select(DriftBottle).where(DriftBottle.id == int(target)))
            if item is None:
                return "没有找到这个漂流瓶。"
            path = Path(item.file_path)
            session.delete(item)
        if str(path) != "." and path.exists():
            os.remove(path)
        return f"已删除漂流瓶 #{target}。"
    return "用法：/扔漂流瓶 或 /丢漂流瓶，按提示发送文字或图片；/捡漂流瓶 或 /捞漂流瓶；/删除漂流瓶 ID（管理员）"


@bottle_cmd.handle()
async def handle_bottle(event: GroupMessageEvent, state: T_State, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    action = raw.split(maxsplit=1)[0].lower() if raw else ""
    payload = raw.split(maxsplit=1)[1:] if raw else []
    if action in {"throw", "toss", "扔", "丢", "投", "add", "添加"} and not _image_urls(args) and not payload:
        await bottle_cmd.send("请发送漂流瓶内容")
        state["waiting_bottle"] = True
        return
    await bottle_cmd.finish(await _handle_bottle(event, raw, args))


@bottle_cmd.got("bottle_content")
async def handle_bottle_content(event: GroupMessageEvent, state: T_State):
    if not state.get("waiting_bottle"):
        return
    await bottle_cmd.finish(await _save_bottle(event, event.get_message()))


@throw_bottle_cmd.handle()
async def handle_throw_bottle_first(event: GroupMessageEvent, state: T_State, args: Message = CommandArg()):
    if _image_urls(args) or _plain_text(args):
        await throw_bottle_cmd.finish(await _save_bottle(event, args))
    await throw_bottle_cmd.send("请发送漂流瓶内容")


@throw_bottle_cmd.got("bottle_content")
async def handle_throw_bottle_content(event: GroupMessageEvent, state: T_State):
    await throw_bottle_cmd.finish(await _save_bottle(event, event.get_message()))


@pick_bottle_cmd.handle()
async def handle_pick_bottle(event: GroupMessageEvent):
    await pick_bottle_cmd.finish(await _pick_bottle())


@delete_bottle_cmd.handle()
async def handle_delete_bottle(event: GroupMessageEvent, args: Message = CommandArg()):
    await delete_bottle_cmd.finish(await _handle_bottle(event, f"delete {args.extract_plain_text().strip()}", args))
