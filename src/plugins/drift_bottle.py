import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from nonebot import logger, on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.typing import T_State
from sqlalchemy import func, select

from src.config import settings
from src.db import DriftBottle, init_db, session_scope
from src.image_utils import download_image, read_image_base64


MAX_PICK_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PICK_IMAGE_SIZE_TEXT = "2MB"
BOTTLE_THROW_ALIASES = {"丢漂流瓶", "投漂流瓶", "扔瓶子", "丢瓶子"}
BOTTLE_PICK_ALIASES = {"捞漂流瓶", "拾漂流瓶", "捡瓶子", "捞瓶子"}
BOTTLE_DELETE_ALIASES = {"删漂流瓶"}
BOTTLE_THROW_ACTIONS = {
    "throw",
    "toss",
    "扔",
    "丢",
    "投",
    "add",
    "添加",
    "扔漂流瓶",
    *BOTTLE_THROW_ALIASES,
}
BOTTLE_PICK_ACTIONS = {
    "pick",
    "捡",
    "捞",
    "拾",
    "random",
    "随机",
    "捡漂流瓶",
    *BOTTLE_PICK_ALIASES,
}
BOTTLE_DELETE_ACTIONS = {"delete", "删除", "删", "删除漂流瓶", *BOTTLE_DELETE_ALIASES}

bottle_cmd = on_command("bottle", aliases={"漂流瓶"}, priority=20, block=True)
throw_bottle_cmd = on_command("扔漂流瓶", aliases=BOTTLE_THROW_ALIASES, priority=20, block=True)
pick_bottle_cmd = on_command("捡漂流瓶", aliases=BOTTLE_PICK_ALIASES, priority=20, block=True)
delete_bottle_cmd = on_command("删除漂流瓶", aliases=BOTTLE_DELETE_ALIASES, priority=20, block=True)


@dataclass(frozen=True)
class PickedBottle:
    id: int
    content_type: str
    content: str
    file_path: str


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


def _is_admin(user_id: str) -> bool:
    return user_id in set(settings.superusers)


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


async def _save_bottle(event: GroupMessageEvent, message: Message, text_override: str | None = None):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    urls = _image_urls(message)
    text = _plain_text(message) if text_override is None else text_override.strip()
    if not urls and not text:
        return "没有收到漂流瓶内容，已取消。"

    downloaded_paths: list[Path] = []
    if urls:
        bottle_dir = _bottle_dir()
        for url in urls:
            filename = f"{group_id}_{user_id}_{secrets.token_hex(8)}.jpg"
            path = bottle_dir / filename
            try:
                await download_image(url, path)
            except Exception as exc:
                for downloaded_path in downloaded_paths:
                    downloaded_path.unlink(missing_ok=True)
                return f"漂流瓶图片保存失败：{exc}"
            downloaded_paths.append(path)

    saved = 0
    try:
        with session_scope() as session:
            for path in downloaded_paths:
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
    except Exception as exc:
        for downloaded_path in downloaded_paths:
            downloaded_path.unlink(missing_ok=True)
        return f"漂流瓶保存失败：{exc}"
    return f"已扔出 {saved} 个漂流瓶。"


def _mark_bottle_picked(bottle_id: int) -> None:
    with session_scope() as session:
        item = session.get(DriftBottle, bottle_id)
        if item is not None:
            item.picked_count += 1


def _format_bottle(item: PickedBottle):
    if item.content_type == "text":
        return f"漂流瓶 #{item.id}：{item.content}"
    path = Path(item.file_path)
    if not path.exists():
        return f"捡到漂流瓶 #{item.id}，但图片文件不存在，可能被手动删除了。"
    size = path.stat().st_size
    logger.info(f"Picked image drift bottle #{item.id}: size={size} path={path}")
    if size > MAX_PICK_IMAGE_BYTES:
        return (
            f"捡到漂流瓶 #{item.id}，但图片大小 {_format_size(size)}，超过 {MAX_PICK_IMAGE_SIZE_TEXT}，"
            f"为避免发送超时已跳过图片。可让管理员检查或删除：/删除漂流瓶 {item.id}"
        )
    try:
        encoded = read_image_base64(path, max_bytes=MAX_PICK_IMAGE_BYTES)
    except Exception as exc:
        return f"捡到漂流瓶 #{item.id}，但图片无法读取：{exc}"
    return MessageSegment.text(f"捡到漂流瓶 #{item.id}：\n") + MessageSegment.image(f"base64://{encoded}")


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
        return PickedBottle(
            id=item.id,
            content_type=item.content_type,
            content=item.content,
            file_path=item.file_path,
        )


async def _send_picked_bottle(matcher, picked):
    if not isinstance(picked, PickedBottle):
        await matcher.finish(picked)
        return

    message = _format_bottle(picked)
    try:
        await matcher.send(message)
    except Exception as exc:
        logger.warning(f"Failed to send drift bottle #{picked.id}: {exc}")
        if picked.content_type != "image":
            return
        fallback = (
            f"捡到漂流瓶 #{picked.id}，但图片发送失败：{str(exc)[:120]}。"
            f"可稍后重试或让管理员删除：/删除漂流瓶 {picked.id}"
        )
        try:
            await matcher.send(fallback)
        except Exception as fallback_exc:
            logger.warning(f"Failed to send drift bottle #{picked.id} fallback: {fallback_exc}")
            return
    _mark_bottle_picked(picked.id)


async def _handle_bottle(event: GroupMessageEvent, raw: str, message: Message):
    init_db()
    action, _, payload = raw.partition(" ")
    action = action.lower()
    user_id = str(event.user_id)
    if action in BOTTLE_THROW_ACTIONS:
        return await _save_bottle(event, message, payload)
    if action in BOTTLE_PICK_ACTIONS:
        return await _pick_bottle()
    if action in BOTTLE_DELETE_ACTIONS:
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
    if action in BOTTLE_THROW_ACTIONS and not _image_urls(args) and not payload:
        state["waiting_bottle"] = True
        return
    if action in BOTTLE_PICK_ACTIONS:
        await _send_picked_bottle(bottle_cmd, await _pick_bottle())
        return
    await bottle_cmd.finish(await _handle_bottle(event, raw, args))


@bottle_cmd.got("bottle_content", prompt="请发送漂流瓶内容")
async def handle_bottle_content(event: GroupMessageEvent, state: T_State):
    if not state.get("waiting_bottle"):
        return
    await bottle_cmd.finish(await _save_bottle(event, event.get_message()))


@throw_bottle_cmd.handle()
async def handle_throw_bottle_first(event: GroupMessageEvent, state: T_State, args: Message = CommandArg()):
    if _image_urls(args) or _plain_text(args):
        await throw_bottle_cmd.finish(await _save_bottle(event, args))


@throw_bottle_cmd.got("bottle_content", prompt="请发送漂流瓶内容")
async def handle_throw_bottle_content(event: GroupMessageEvent, state: T_State):
    await throw_bottle_cmd.finish(await _save_bottle(event, event.get_message()))


@pick_bottle_cmd.handle()
async def handle_pick_bottle(event: GroupMessageEvent):
    await _send_picked_bottle(pick_bottle_cmd, await _pick_bottle())


@delete_bottle_cmd.handle()
async def handle_delete_bottle(event: GroupMessageEvent, args: Message = CommandArg()):
    await delete_bottle_cmd.finish(await _handle_bottle(event, f"delete {args.extract_plain_text().strip()}", args))
