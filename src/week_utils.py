import re
from datetime import datetime


def week_number_for(date_text: str, start_date: str) -> int | None:
    if not date_text or not start_date:
        return None
    current = datetime.strptime(date_text, "%Y-%m-%d").date()
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    delta = (current - start).days
    if delta < 0:
        return None
    return delta // 7 + 1


def _expand_week_numbers(value: str) -> set[int]:
    result: set[int] = set()
    for part in re.split(r"[，,、\s]+", value):
        part = part.strip()
        if not part:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start <= end:
                result.update(range(start, end + 1))
            continue
        if part.isdigit():
            result.add(int(part))
    return result


def is_valid_week_rule(weeks: str) -> bool:
    rule = (weeks or "").strip()
    if not rule or rule in {"全部", "每周", "all", "ALL"}:
        return True

    odd_only = "单" in rule or "odd" in rule.lower()
    even_only = "双" in rule or "even" in rule.lower()
    number_rule = re.sub(r"(单周|双周|单|双|odd|even|周|第)", "", rule, flags=re.IGNORECASE).strip()
    if not number_rule:
        return odd_only or even_only

    for part in re.split(r"[，,、\s]+", number_rule):
        part = part.strip()
        if not part:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start < 1 or end < start:
                return False
            continue
        if not part.isdigit() or int(part) < 1:
            return False
    return True


def is_week_enabled(weeks: str, week_number: int | None) -> bool:
    rule = (weeks or "").strip()
    if not rule or rule in {"全部", "每周", "all", "ALL"}:
        return True
    if week_number is None:
        return True

    odd_only = "单" in rule or "odd" in rule.lower()
    even_only = "双" in rule or "even" in rule.lower()
    number_rule = re.sub(r"(单周|双周|单|双|odd|even|周|第)", "", rule, flags=re.IGNORECASE).strip()
    numbers = _expand_week_numbers(number_rule)

    if numbers and week_number not in numbers:
        return False
    if odd_only and week_number % 2 != 1:
        return False
    if even_only and week_number % 2 != 0:
        return False
    if not numbers and not odd_only and not even_only:
        return True
    return True


def describe_week_rule(weeks: str) -> str:
    return (weeks or "").strip() or "每周"
