# QQ Course Bot v1

第一版功能：

- NapCatQQ + OneBot v11 反向 WebSocket 接入
- 群聊内回复
- 个人 todo list
- todo 定期/到期提醒
- 重要日程每天 08:00 倒计时提醒
- CSV 课程表导入
- 上课前 15 分钟提醒
- 临时加课、停课、调课
- 黑历史图片/文字上传、随机发送、列表和删除治理
- 全群共享漂流瓶
- OpenAI-compatible API 闲聊，默认 OpenAI `gpt-4o`

## 本地运行

```powershell
cd D:\qq-bot-v1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python bot.py
```

启动后，Bot 会监听：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

## NapCatQQ 配置

在 NapCat WebUI 里添加 OneBot v11 WebSocket 客户端：

```text
连接类型：WebSocket Client / 反向 WebSocket
URL：ws://127.0.0.1:8080/onebot/v11/ws
```

然后把 bot QQ 号拉进测试群，在群里发送：

```text
/help
```

更细的本地验收步骤见 [docs/local-test.md](docs/local-test.md)。

## 命令

### Todo

添加 todo：

```text
/todo add 三天 高数作业 每 1 天
```

设置开始和结束时间：

```text
/todo add 明天 09:00-11:00 高数作业
/todo add 开始 明天09:00 结束 明天11:00 高数作业
/todo add 截止 明天20:00 高数作业
```

有截止时间的 todo 会在截止前 24 小时内，每 2 小时提醒一次。

含义：

- `三天`：截止时间，可写 `2026/6/15`、`2026-06-15 20:00`、`明天`、`三天`；未写具体时间默认中午 12:00
- `高数作业`：任务内容
- `每 1 天`：每 1 天重复提醒，可省略；也支持 `每 60 分钟`

查看 todo：

```text
/todo list
```

完成 todo：

```text
/todo done 1
/todo done 高数作业
```

删除 todo：

```text
/todo delete 1
/todo delete 高数作业
```

### 重要日程

添加重要日程：

```text
/重要日程 add 2026-06-20 考试
/添加重要日程 2026-06-20 考试
```

bot 会在每天早上 08:00 发送倒计时提醒，提醒发到创建日程的群并 @ 创建人。

查看和删除：

```text
/重要日程 list
/重要日程 delete 1
/查看重要日程
/删除重要日程 1
```

### 课程表

查看 CSV 示例：

```text
/course sample
```

导入课程表：

```text
/course import course_name,weekday,start_time,end_time,start_date,end_date,location,teacher,weeks
高等数学,1,08:00,09:40,2026-09-01,2027-01-10,A101,张老师,1-16
大学英语,3,14:00,15:40,2026-09-01,2027-01-10,B203,李老师,1-16单周
体育,5,10:00,11:40,2026-09-01,2027-01-10,操场,王老师,2-16双周
```

`weeks` 支持：

```text
1-16
1,3,5
单周
双周
1-16单周
2-16双周
```

查看课程表：

```text
/course list
```

清空课程表：

```text
/course clear
```

临时取消、添加、调课：

```text
/删除课程 2026-10-01 all
/删除课程 2026-10-01 高等数学
/添加课程 2026-10-08 08:00-09:40 线代补课 A101
/移动课程 高等数学 2026-10-01 2026-10-08 10:00-11:40 A101
```

### 黑历史

所有群成员都可以添加黑历史；删除仍限制为记录创建者、群管理员或 bot 管理员。

先发送命令：

```text
/添加黑历史
```

bot 回复“请发送黑历史”后，再发送图片或文字。

随机发送本群保存过的黑历史，会附带 ID：

```text
/随机黑历史
```

查看最近 10 条记录：

```text
/黑历史 list
```

删除黑历史允许记录创建者、群管理员或 bot 管理员操作：

```text
/删除黑历史 1
```

### 漂流瓶

所有群成员都可以扔漂流瓶：

```text
/扔漂流瓶
```

bot 回复“请发送漂流瓶内容”后，再发送文字或图片。也可以直接写：

```text
/bottle throw 今天也要好好吃饭
```

捡漂流瓶会从所有群共享的漂流瓶里随机抽取一个：

```text
/捡漂流瓶
/bottle pick
```

删除漂流瓶仅 bot 管理员可用：

```text
/删除漂流瓶 1
/bottle delete 1
```

### AI

```text
/ai 你好
```

也支持在群里 @bot 触发闲聊。

## AI 小模型

默认配置按 OpenAI Chat Completions API 写：

```text
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=你的APIKey
AI_MODEL=gpt-4o
```

如果你换其他兼容 OpenAI Chat Completions 的服务，只要改 `.env` 的 `AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`。

## 服务器迁移

本项目已尽量规避 Windows/Linux 差异：

- 配置放 `.env`
- 数据库默认 `./data/bot.db`
- 时区固定 `Asia/Shanghai`
- NapCat 和 Bot 只通过 WebSocket 通讯

服务器上建议用 Docker 跑 Bot 程序，NapCatQQ 也用官方推荐的 Linux/Docker 方式运行。

## Docker

```bash
docker compose up -d --build
```

默认 Docker Compose 只把 `8080` 绑定到宿主机 `127.0.0.1`，不要直接暴露到公网。如果 NapCat 和 Bot 在同一台服务器的 Docker 网络里，WebSocket 地址按实际网络改成：

```text
ws://qq-bot:8080/onebot/v11/ws
```

或者使用宿主机本机地址：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

如果 NapCat 不在同一台机器，建议走内网、SSH 隧道、反向代理鉴权或防火墙白名单，不建议直接开放 OneBot WebSocket 到公网。
