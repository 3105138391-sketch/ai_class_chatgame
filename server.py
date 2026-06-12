import json
import os
import re
import time
import http.server
import socketserver
from urllib import error, request
from urllib.parse import unquote, urlparse

PORT = int(os.environ.get("PORT", 8080))
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_CREATE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

PUBLIC_ASSET_PREFIX = "assets/"
PUBLIC_ASSET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico", ".mp3", ".wav", ".ogg"}
BLOCKED_FILE_NAMES = {
    "index.html",
    "server.py",
    "Dockerfile",
    "render.yaml",
    "requirements.txt",
    "README.md",
    ".dockerignore",
    ".env",
    ".env.example",
}
BLOCKED_PATH_PARTS = {"..", ".git", "__pycache__", ".venv", "venv", "node_modules"}
BLOCKED_EXTENSIONS = {
    ".py", ".pyc", ".env", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".txt", ".log", ".zip", ".tar", ".gz", ".rar", ".7z",
}

Handler = http.server.SimpleHTTPRequestHandler


def fallback_blueprint(source_title="西游记古文版"):
    return {
        "title": "西游灵境：取经劫",
        "sourceTitle": source_title,
        "worldSummary": "三界分立，四大部洲各有气运。天庭掌秩序，西天定因果，地府录生死，龙宫辖水脉，人间国度与洞府妖国夹在神佛法度和凡心欲念之间。取经路不是单线旅程，而是一场关于修心、劫难、名号与因果的开放试炼。",
        "coreConflict": "经卷、功德、妖心、天条与凡人愿望互相牵扯。玩家既要在劫难中求生，也要判断每个妖国、仙府和人间城池背后的因果。",
        "tone": "章回体神魔小说气质，现代可读，行动清晰，带一点古意和黑绿色终端感。",
        "visualStyle": "高质量暗色东方神魔场景，古典山水、幽绿法光、神佛云纹、电影感构图，适合作为文字游戏背景",
        "factions": [
            {"name": "取经一行", "goal": "西行求取真经，历劫修心"},
            {"name": "天庭", "goal": "维持三界名册、天条与神职秩序"},
            {"name": "西天佛门", "goal": "布设因果试炼，度化众生"},
            {"name": "洞府妖国", "goal": "求长生、争名号、避天劫或夺功德"},
            {"name": "人间诸国", "goal": "在妖患、信仰和王权之间求安稳"}
        ],
        "locations": [
            {"name": "花果山", "keywords": ["花果山", "水帘洞", "灵猴"]},
            {"name": "长安城", "keywords": ["长安", "唐王", "人间"]},
            {"name": "流沙河", "keywords": ["流沙河", "弱水", "沙"]},
            {"name": "云栈洞", "keywords": ["云栈洞", "高老庄", "猪"]},
            {"name": "西天雷音", "keywords": ["西天", "灵山", "雷音"]}
        ],
        "mainQuests": [
            {"title": "开局入劫", "keywords": ["开局", "入劫", "身份"]},
            {"title": "取经路启", "keywords": ["取经", "西行", "长安"]},
            {"title": "洞府妖国", "keywords": ["妖国", "洞府", "妖王"]},
            {"title": "天庭名册", "keywords": ["天庭", "仙班", "名册"]},
            {"title": "灵山问心", "keywords": ["灵山", "雷音", "真经"]}
        ],
        "sideQuests": [
            {"title": "龙宫旧契", "keywords": ["龙宫", "龙王", "水族"]},
            {"title": "地府残页", "keywords": ["地府", "生死簿", "阎君"]},
            {"title": "凡国妖患", "keywords": ["国王", "城池", "妖患"]},
            {"title": "花果山余脉", "keywords": ["花果山", "猴群", "水帘洞"]}
        ],
        "identitySuggestions": [
            {"name": "取经路随行弟子", "description": "懂佛经皮毛，能记功过，也最容易被卷入劫难。"},
            {"name": "花果山新灵猴", "description": "身手轻快，熟悉妖族规矩，却未见过天庭真正威严。"},
            {"name": "天庭司簿小吏", "description": "掌一点名册文牒，知道神职漏洞，也背着天条压力。"},
            {"name": "龙宫巡海夜叉", "description": "通水脉、识宝器，在陆上行动却常受限制。"},
            {"name": "西牛贺洲散修", "description": "懂符箓与山野传闻，立场自由但根基不稳。"}
        ],
        "scenes": [
            {"label": "花果山水帘洞", "keywords": ["花果山", "水帘洞", "灵猴"], "prompt": "花果山水帘洞，瀑布如白练，石桥幽绿法光，群猴远望，东方神魔电影感背景"},
            {"label": "长安夜市", "keywords": ["长安", "人间", "唐王"], "prompt": "唐代长安夜色，灯火、经卷、官道与远处寺塔，暗色东方奇幻，适合作为文字冒险背景"},
            {"label": "洞府妖国", "keywords": ["妖国", "洞府", "妖王"], "prompt": "山腹洞府妖国，石殿、旌旗、幽火、妖王宝座，古典神魔小说氛围，高质量场景背景"},
            {"label": "灵山云路", "keywords": ["西天", "灵山", "雷音"], "prompt": "西天灵山云路，金色佛光被青绿云气包围，远处雷音寺若隐若现，电影感东方神话背景"}
        ],
        "gmPrompt": ""
    }


def build_gm_prompt(blueprint):
    title = blueprint.get("title") or "AI 文字游戏"
    return f"""你是《{title}》的文字游戏主持人。你要基于用户提供或系统生成的世界观，主持一场可互动的中文文字冒险。

【世界观摘要】
{blueprint.get("worldSummary", "")}

【核心冲突】
{blueprint.get("coreConflict", "")}

【叙事风格】
{blueprint.get("tone", "沉浸、清晰、可行动，每次推动一小段剧情。")}

【主持规则】
1. 每次回复 220-450 字，第三人称叙述，NPC 对白用「」。
2. 允许玩家自由输入行动；你也必须在末尾给出 A-D 四个选项。
3. 不要替玩家做重大选择。不要一回合解决整条主线。
4. 回复末尾必须包含状态栏，格式：
📍 地点 | 📌 阶段 | 🎭 身份/立场 | 🧭 目标 | ✨ 线索/资源
5. 选项格式严格使用：
A. 选项一
B. 选项二
C. 选项三
D. 选项四
6. 可以出现冲突、危机、斗法、追逐和辩论，但避免血腥细节和现实伤害指导。
7. 如果玩家要求结束、退出或谢幕，引导其使用结束按钮或总结当前旅程。
"""


def complete_blueprint(blueprint):
    base = fallback_blueprint(blueprint.get("sourceTitle") or "西游记古文版")
    merged = {**base, **{k: v for k, v in blueprint.items() if v not in (None, "", [])}}
    for key in ["factions", "locations", "mainQuests", "sideQuests", "identitySuggestions", "scenes"]:
        if not isinstance(merged.get(key), list) or not merged[key]:
            merged[key] = base[key]
    if not merged.get("gmPrompt"):
        merged["gmPrompt"] = build_gm_prompt(merged)
    return merged


class MyHandler(Handler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_not_found(self, head_only=False):
        body = b"Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _open_json(self, req, timeout):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, json.loads(body) if body else {}
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {"message": body}
            return exc.code, payload

    def _post_json(self, url, payload, headers, timeout=60):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method="POST")
        return self._open_json(req, timeout)

    def _get_json(self, url, headers, timeout=30):
        req = request.Request(url, headers=headers, method="GET")
        return self._open_json(req, timeout)

    def _is_public_asset(self, requested_path):
        if not requested_path.startswith(PUBLIC_ASSET_PREFIX):
            return False
        _, ext = os.path.splitext(requested_path.lower())
        return ext in PUBLIC_ASSET_EXTENSIONS

    def _is_blocked_path(self, requested_path):
        normalized = requested_path.strip("/")
        if not normalized:
            return False
        parts = [part for part in normalized.split("/") if part]
        if any(part in BLOCKED_PATH_PARTS or part.startswith(".") for part in parts):
            return True
        filename = parts[-1]
        if filename in BLOCKED_FILE_NAMES:
            return True
        _, ext = os.path.splitext(filename.lower())
        return ext in BLOCKED_EXTENSIONS

    def _route_static_request(self, head_only=False):
        requested_path = unquote(urlparse(self.path).path).lstrip("/")
        if requested_path and self._is_blocked_path(requested_path):
            return self._send_not_found(head_only=head_only)
        if requested_path and os.path.isfile(requested_path):
            if not self._is_public_asset(requested_path):
                return self._send_not_found(head_only=head_only)
            return Handler.do_HEAD(self) if head_only else Handler.do_GET(self)
        self.path = "/index.html"
        return Handler.do_HEAD(self) if head_only else Handler.do_GET(self)

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return
        if self.path.startswith("/api/"):
            self._send_json(404, {"message": "接口不存在"})
            return
        return self._route_static_request()

    def do_HEAD(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", "12")
            self.end_headers()
            return
        if self.path.startswith("/api/"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self._route_static_request(head_only=True)

    def do_POST(self):
        if self.path == "/api/chat":
            return self.handle_chat()
        if self.path == "/api/image":
            return self.handle_image()
        if self.path == "/api/generate-game":
            return self.handle_generate_game()
        if self.path == "/api/start-game":
            return self.handle_start_game()
        self._send_json(404, {"message": "接口不存在"})

    def deepseek_chat(self, messages, temperature=0.8, max_tokens=1800):
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        status, data = self._post_json(
            DEEPSEEK_URL,
            payload,
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=90,
        )
        if status >= 400:
            raise RuntimeError(data.get("message") or data.get("error", {}).get("message") or f"DeepSeek 返回 {status}")
        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            raise RuntimeError("DeepSeek 未返回文本内容")
        return content.strip()

    def extract_json_object(self, text):
        cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if not match:
                raise
            return json.loads(match.group(0))

    def handle_chat(self):
        try:
            payload = self._read_json()
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                self._send_json(200, {"choices": [{"message": {"content": self.fallback_chat(payload)}}], "fallback": True})
                return
            status, data = self._post_json(
                DEEPSEEK_URL,
                payload,
                {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=90,
            )
            self._send_json(status, data)
        except Exception as exc:
            self._send_json(500, {"message": f"对话接口调用失败: {exc}"})

    def fallback_chat(self, payload):
        messages = payload.get("messages") or []
        last_user = next((msg.get("content", "") for msg in reversed(messages) if msg.get("role") == "user"), "继续观察")
        return f"""你选择了「{last_user}」。风声在暗处一顿，像有无形的手翻过命簿。前方的灯火忽明忽暗，一名披旧袈裟的行脚人从巷尾转出，低声提醒：「此事不可只看表象。若你要追线索，先分清是妖气、天命，还是人心作祟。」

你脚边的尘土浮起细小光痕，残缺通关文牒又显出一行新字：第一场劫难已经开始回应你的选择。

📍 花果山 | 📌 线索初显 | 🎭 当前身份 | 🧭 追查劫难源头 | ✨ 通关文牒微光

A. 追问行脚人的真实身份
B. 顺着光痕寻找妖气来源
C. 检查通关文牒的新字
D. 暂时退入暗处，观察局势变化"""

    def handle_generate_game(self):
        payload = self._read_json()
        source_title = str(payload.get("sourceTitle") or "西游记古文版").strip()
        source_text = str(payload.get("sourceText") or "").strip()
        if not os.environ.get("DEEPSEEK_API_KEY"):
            blueprint = complete_blueprint(fallback_blueprint(source_title))
            self._send_json(200, {"blueprint": blueprint, "fallback": True})
            return
        system = """你是文字游戏设计师。请把用户提供的小说故事、古典文本或世界观，改造成可运行的中文文字冒险游戏蓝图。
只输出 JSON，不要 Markdown。JSON 必须包含：
title, sourceTitle, worldSummary, coreConflict, tone, visualStyle,
factions[{name,goal}], locations[{name,keywords}], mainQuests[{title,keywords}],
sideQuests[{title,keywords}], identitySuggestions[{name,description}],
scenes[{label,keywords,prompt}], gmPrompt。
gmPrompt 必须是完整系统提示词，要求主持人每轮 220-450 字，末尾包含状态栏和 A-D 四个选项。"""
        user = f"来源标题：{source_title}\n\n故事/世界观材料：\n{source_text[:6000]}"
        try:
            content = self.deepseek_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.55,
                max_tokens=3200,
            )
            blueprint = complete_blueprint(self.extract_json_object(content))
            blueprint["sourceTitle"] = source_title
            self._send_json(200, {"blueprint": blueprint, "fallback": False})
        except Exception as exc:
            blueprint = complete_blueprint(fallback_blueprint(source_title))
            self._send_json(200, {"blueprint": blueprint, "fallback": True, "message": str(exc)})

    def handle_start_game(self):
        payload = self._read_json()
        blueprint = complete_blueprint(payload.get("blueprint") or fallback_blueprint())
        identity = str(payload.get("identity") or "无名旅人").strip()
        if not os.environ.get("DEEPSEEK_API_KEY"):
            opening = self.fallback_opening(blueprint, identity)
            self._send_json(200, {"opening": opening, "fallback": True})
            return
        prompt = f"""请基于以下游戏蓝图和玩家身份，写第一幕开场。
要求：220-450 字；第三人称；NPC 对白用「」；末尾必须有状态栏和 A-D 四个选项。
状态栏格式：📍 地点 | 📌 阶段 | 🎭 身份/立场 | 🧭 目标 | ✨ 线索/资源

游戏蓝图：
{json.dumps(blueprint, ensure_ascii=False)[:8000]}

玩家身份：{identity}"""
        try:
            opening = self.deepseek_chat(
                [{"role": "system", "content": blueprint.get("gmPrompt") or build_gm_prompt(blueprint)}, {"role": "user", "content": prompt}],
                temperature=0.85,
                max_tokens=1600,
            )
            self._send_json(200, {"opening": opening, "fallback": False})
        except Exception as exc:
            self._send_json(200, {"opening": self.fallback_opening(blueprint, identity), "fallback": True, "message": str(exc)})

    def fallback_opening(self, blueprint, identity):
        first_location = (blueprint.get("locations") or [{"name": "长安城"}])[0].get("name", "长安城")
        title = blueprint.get("title", "文字游戏")
        return f"""夜色像一页被墨浸过的经卷，缓缓压在{first_location}上。{identity}站在风口，听见远处钟声与妖气同时掠过屋脊。街角老僧低声道：「此去不是寻常赶路，是入劫。你若只问胜负，便会错过因果；你若只问因果，又未必走得出生死。」

一枚残缺的通关文牒被递到你掌心，纸面浮出{title}四字，又很快被幽绿法光吞没。前路有神佛、有妖国、有凡人城池，也有你自己的来处和名号。

📍 {first_location} | 📌 开局入劫 | 🎭 {identity} | 🧭 查明第一场劫难 | ✨ 残缺通关文牒

A. 询问老僧第一场劫难的来历
B. 检查残缺通关文牒上的暗纹
C. 前往城门，观察来往人妖踪迹
D. 隐藏身份，先在市井中打听消息"""

    def handle_image(self):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            self._send_json(200, {"url": None, "skipped": True, "message": "缺少环境变量 DASHSCOPE_API_KEY"})
            return
        try:
            payload = self._read_json()
            scene = str(payload.get("scene") or "").strip()
            prompt = "高质量文字冒险场景背景，暗色东方奇幻，电影感，适合作为网页游戏背景，" + (
                scene or "古典神魔世界，幽绿法光，山水与云气"
            )
            create_payload = {
                "model": os.environ.get("DASHSCOPE_IMAGE_MODEL", "wanx2.0-t2i-turbo"),
                "input": {"prompt": prompt[:800]},
                "parameters": {
                    "size": os.environ.get("DASHSCOPE_IMAGE_SIZE", "1024*1024"),
                    "n": 1,
                    "prompt_extend": True,
                    "watermark": False,
                },
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            status, data = self._post_json(DASHSCOPE_CREATE_URL, create_payload, headers)
            if status >= 400:
                self._send_json(status, data)
                return
            results = data.get("output", {}).get("results") or []
            if results and results[0].get("url"):
                self._send_json(200, {"url": results[0]["url"]})
                return
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                self._send_json(502, {"message": "DashScope 未返回 task_id", "detail": data})
                return
            poll_interval = int(os.environ.get("DASHSCOPE_POLL_INTERVAL", "10"))
            max_attempts = int(os.environ.get("DASHSCOPE_MAX_POLLS", "12"))
            poll_headers = {"Authorization": f"Bearer {api_key}"}
            for _ in range(max_attempts):
                time.sleep(poll_interval)
                poll_status, poll_data = self._get_json(DASHSCOPE_TASK_URL.format(task_id=task_id), poll_headers)
                if poll_status >= 400:
                    self._send_json(poll_status, poll_data)
                    return
                output = poll_data.get("output", {})
                task_status = output.get("task_status")
                if task_status == "SUCCEEDED":
                    results = output.get("results") or []
                    if results and results[0].get("url"):
                        self._send_json(200, {"url": results[0]["url"], "task_id": task_id})
                        return
                    self._send_json(502, {"message": "DashScope 任务成功但未返回图片 URL", "detail": poll_data})
                    return
                if task_status in {"FAILED", "CANCELED", "UNKNOWN"}:
                    self._send_json(502, {"message": f"DashScope 生图任务失败: {task_status}", "detail": poll_data})
                    return
            self._send_json(504, {"message": "DashScope 生图超时", "task_id": task_id})
        except Exception as exc:
            self._send_json(500, {"message": f"生图接口调用失败: {exc}"})


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


with ReusableTCPServer(("0.0.0.0", PORT), MyHandler) as httpd:
    print(f"AI 文字游戏生成器服务器启动 - 端口 {PORT}")
    httpd.serve_forever()
