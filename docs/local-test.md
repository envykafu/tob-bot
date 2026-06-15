# Local Test Checklist

## 1. Start bot

```powershell
cd D:\qq-bot-v1
.\.venv\Scripts\Activate.ps1
python bot.py
```

Expected log:

```text
Uvicorn running on http://127.0.0.1:8080
Loaded adapters: OneBot V11
```

## 2. Connect NapCatQQ

In NapCat WebUI, add OneBot v11 reverse WebSocket:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

The bot console should show a connection log after NapCat connects.

## 3. Test commands in QQ group

```text
/help
/todo add 三天 测试任务 每 1 天
/todo list
/todo done 1
/course sample
```

## 4. Test course import

```text
/course import course_name,weekday,start_time,end_time,start_date,end_date,location,teacher,weeks
高等数学,1,08:00,09:40,2026-09-01,2027-01-10,A101,张老师,1-16
大学英语,3,14:00,15:40,2026-09-01,2027-01-10,B203,李老师,1-16单周
体育,5,10:00,11:40,2026-09-01,2027-01-10,操场,王老师,2-16双周
```

Then:

```text
/course list
```

## 5. Test AI

Configure `AI_API_KEY` in `.env`, then:

```text
/ai 你好
```

If AI is not running, command handling should still work, but `/ai` will report connection failure.

## 6. Test black history

Send:

```text
/添加黑历史
```

After the bot replies, send an image or text.

Then:

```text
/black random
```

## 7. Test course adjustments

```text
/删除课程 2026-10-01 all
/删除课程 2026-10-01 高等数学
/添加课程 2026-10-08 08:00-09:40 线代补课 A101
/移动课程 高等数学 2026-10-01 2026-10-08 10:00-11:40 A101
```
