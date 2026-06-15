from nonebot.adapters.onebot.v11 import MessageSegment


def at_user(user_id: str) -> MessageSegment:
    return MessageSegment.at(int(user_id))
