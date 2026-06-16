import httpx
import json
import re

from src.config import settings


SYSTEM_PROMPT = (
    "你是QQ群里的可爱猫娘助手。"
    "请用中文直接回答用户问题，语气自然友好，句尾可以适度加“喵”。"
    "遇到数学证明、代码、长解释或复杂问题时，优先保证结论完整、步骤清晰，不要为了卖萌牺牲准确性。"
    "用户问课程表、todo、黑历史、漂流瓶或重要日程命令时，提醒使用 /help 或 /readme。"
)


FINAL_ONLY_SYSTEM_PROMPT = "你是QQ群里的中文助手。不要输出思考过程，只输出完整最终答案；如果是证明题，请给出清晰步骤。"


def _finish_reason(data: dict) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0] or {}
    return str(choice.get("finish_reason") or "")


def _extract_content(data: dict) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0] or {}
    message_obj = choice.get("message") or {}
    delta_obj = choice.get("delta") or {}
    content = message_obj.get("content") or delta_obj.get("content") or ""
    content = str(content).strip()
    return content or None


def _build_messages(message: str, history: list[dict[str, str]] | None, system_prompt: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    for item in history or []:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


async def _request_once(url: str, headers: dict[str, str], payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"请求超时，当前超时设置为 {settings.ai_timeout_seconds} 秒") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"请求失败：{exc}") from exc
    if response.status_code >= 400:
        if response.status_code == 401:
            raise RuntimeError("HTTP 401：API Key 未授权或已失效，请检查 .env 中的 AI_API_KEY。")
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


async def chat(
    message: str,
    user_id: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    if not settings.ai_enabled:
        return "AI 闲聊当前未开启。", []
    if not settings.ai_api_key:
        return "AI_API_KEY 还没有配置。请先在 .env 里填写 API Key。", []

    url = settings.ai_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.ai_api_key}"}
    base_messages = _build_messages(message, history, SYSTEM_PROMPT)
    payload = {
        "model": settings.ai_model,
        "messages": base_messages,
        "temperature": 0.5,
        "max_tokens": settings.ai_max_tokens,
    }
    data = await _request_once(url, headers, payload)
    content = _extract_content(data)
    if content:
        if _finish_reason(data) == "length":
            content = f"{content}\n\n（回复已接近模型输出上限，如需更完整版本请引用这条消息继续问“继续”。）"
        updated_messages = [*base_messages[1:], {"role": "assistant", "content": content}]
        return content, updated_messages

    # DeepSeek reasoner/proxy combinations can consume the small output budget
    # on internal reasoning and return an empty final content. Retry with a
    # shorter system prompt and explicit final-answer instruction.
    retry_messages = _build_messages(message, history, FINAL_ONLY_SYSTEM_PROMPT)
    retry_payload = {
        "model": settings.ai_model,
        "messages": retry_messages,
        "temperature": 0.3,
        "max_tokens": settings.ai_max_tokens,
    }
    data = await _request_once(url, headers, retry_payload)
    content = _extract_content(data)
    if content:
        if _finish_reason(data) == "length":
            content = f"{content}\n\n（回复已接近模型输出上限，如需更完整版本请引用这条消息继续问“继续”。）"
        updated_messages = [*retry_messages[1:], {"role": "assistant", "content": content}]
        return content, updated_messages
    if _finish_reason(data) == "length":
        raise RuntimeError("模型输出预算不足导致最终答案为空，请调大 AI_MAX_TOKENS 后重试。")
    raise RuntimeError("模型服务返回了空结果，请稍后重试或更换模型。")


def config_summary() -> str:
    key_status = "configured" if settings.ai_api_key else "missing"
    return (
        f"AI_BASE_URL={settings.ai_base_url}\n"
        f"AI_MODEL={settings.ai_model}\n"
        f"AI_API_KEY={key_status}"
    )


async def parse_todo_intent(message: str) -> dict | None:
    if not settings.ai_enabled or not settings.ai_api_key:
        return None
    url = settings.ai_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.ai_api_key}"}
    payload = {
        "model": settings.ai_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你只负责把用户中文自然语言解析为todo添加意图。"
                    "只输出JSON，不要输出解释。"
                    "如果不是提醒/todo/截止/待办意图，输出 {\"intent\":\"chat\"}。"
                    "如果是，输出 {\"intent\":\"todo_add\",\"content\":\"任务内容\",\"time_text\":\"时间文本\",\"remind_every_minutes\":null}。"
                    "content 只保留真正事项，去掉“我有一个/我要/记得/提醒我/每天提醒我”等口语。"
                    "time_text 保留用户原话里的截止或发生时间，例如：三天后、明天20:00、明天晚上八点、2026/6/15。"
                    "如果用户说每天/每日提醒，把 remind_every_minutes 设为 1440；每小时设为60；每两天设为2880；每n天提醒一次设为 n*1440。"
                    "例：三天后我有一个考试，记得每天提醒我 => {\"intent\":\"todo_add\",\"content\":\"考试\",\"time_text\":\"三天后\",\"remind_every_minutes\":1440}。"
                ),
            },
            {"role": "user", "content": message},
        ],
        "temperature": 0,
        "max_tokens": 160,
    }
    try:
        data = await _request_once(url, headers, payload)
    except Exception:
        return None
    content = _extract_content(data)
    if not content:
        return None
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if parsed.get("intent") != "todo_add":
        return None
    task = str(parsed.get("content") or "").strip()
    time_text = str(parsed.get("time_text") or "").strip()
    if not task or not time_text:
        return None
    return {
        "content": task,
        "time_text": time_text,
        "remind_every_minutes": parsed.get("remind_every_minutes"),
    }
