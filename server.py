import json
import os
import re
import time
import uuid
import http.server
import socketserver
from urllib import error, request
from urllib.parse import unquote, urlparse
from collections import defaultdict
from threading import Lock

# ─── Config ───────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8080))
MAX_REQUEST_SIZE = 1 * 1024 * 1024       # 1 MB 请求体上限
IMAGE_CACHE_MAX = 200                     # 图片缓存条目上限
SAVES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_CREATE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

PUBLIC_ASSET_PREFIX = "assets/"
PUBLIC_ASSET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico", ".mp3", ".wav", ".ogg", ".css", ".js", ".json", ".woff", ".woff2", ".ttf"}
BLOCKED_FILE_NAMES = {
    "index.html", "server.py", "Dockerfile", "render.yaml",
    "requirements.txt", "README.md", ".dockerignore", ".env", ".env.example",
}
BLOCKED_PATH_PARTS = {"..", ".git", "__pycache__", ".venv", "venv", "node_modules"}
BLOCKED_EXTENSIONS = {
    ".py", ".pyc", ".env", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".txt", ".log", ".zip", ".tar", ".gz", ".rar", ".7z",
}

Handler = http.server.SimpleHTTPRequestHandler

# ─── Rate Limiter ─────────────────────────────────────────────────────────────
# In-memory sliding window: {client_key: [timestamp, ...]}
_RATELIMIT_LOCK = Lock()
_RATELIMIT_BUCKETS = defaultdict(list)

# Per-endpoint rate limits (requests per minute)
RATELIMIT_CONFIG = {
    # path_prefix: (max_requests, window_seconds)
    "/api/chat":      (20, 60),      # Chat is expensive
    "/api/image":     (10, 60),      # Image gen costs real money
    "/api/generate-game": (6, 60),  # Calls DeepSeek
    "/api/start-game":    (10, 60), # Calls DeepSeek
    "/api/save":      (30, 60),
    "default":        (60, 60),      # Load/presets/anything else
}

def _check_ratelimit(client_key, path):
    """Returns True if allowed, False if rate limited."""
    for prefix, (max_req, window) in RATELIMIT_CONFIG.items():
        if path.startswith(prefix):
            break
    else:
        max_req, window = RATELIMIT_CONFIG["default"]

    now = time.time()
    cutoff = now - window
    with _RATELIMIT_LOCK:
        timestamps = _RATELIMIT_BUCKETS[client_key]
        # Prune old entries
        _RATELIMIT_BUCKETS[client_key] = [t for t in timestamps if t > cutoff]
        if len(_RATELIMIT_BUCKETS[client_key]) >= max_req:
            return False
        _RATELIMIT_BUCKETS[client_key].append(now)
        return True


def _get_client_key(handler):
    """Get a rate-limit key for the current request.
    Prefers X-Forwarded-For when behind a reverse proxy, falls back to client IP.
    """
    forwarded = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return handler.client_address[0]


# ─── Image Cache ──────────────────────────────────────────────────────────────
_image_cache = {}  # scene_prompt → {"url": str, "ts": float}

def _cache_get(scene):
    ttl = 3600  # 1 hour TTL
    entry = _image_cache.get(scene)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["url"]
    if entry:
        del _image_cache[scene]
    return None

def _cache_set(scene, url):
    if len(_image_cache) >= IMAGE_CACHE_MAX:
        # evict oldest
        oldest = min(_image_cache.keys(), key=lambda k: _image_cache[k]["ts"])
        del _image_cache[oldest]
    _image_cache[scene] = {"url": url, "ts": time.time()}

# ─── Built-in Presets ─────────────────────────────────────────────────────────
PRESETS = {
    "xiyouji": {
        "title": "西游记古文版",
        "description": "参考公版《西游记》原文体系，生成三界、取经、劫难、妖国、天庭与西天秩序下的互动文字游戏。",
        "sourceUrl": "https://zh.wikisource.org/zh-hans/%E8%A5%BF%E6%B8%B8%E8%A8%98",
        "sourceText": "《西游记》古文版世界观摘要：\n- 世界结构：三界、四大部洲、天庭、西天、地府、龙宫、洞府妖国、人间国度。\n- 核心主题：取经、修心、劫难、神魔秩序、佛道体系、因果试炼。\n- 关键角色可作为 NPC 或势力出现：唐僧、孙悟空、猪八戒、沙僧、观音、玉帝、龙王、阎君、妖王。\n- 叙事应贴近章回体神魔小说气质，但文字游戏回复要现代可读、可操作。\n来源：https://zh.wikisource.org/zh-hans/西游記",
    },
    "fengshen": {
        "title": "封神演义",
        "description": "参考《封神演义》体系，在商周交替、仙妖乱世的神魔战争中，介入阐截之争、封神大劫。",
        "sourceUrl": None,
        "sourceText": "《封神演义》世界观摘要：\n- 时代背景：商朝末年，纣王无道，天下大乱。周武王起兵伐纣，引发三教（阐教、截教、人道）全面冲突。\n- 核心主题：天命劫数、仙妖斗法、封神榜、王朝更替、师徒因果。\n- 关键阵营：阐教（姜子牙、哪吒、杨戬等）、截教（通天教主、多宝道人、赵公明等）、商朝（纣王、妲己、闻仲）、周朝（武王、周公）。\n- 法宝与神通体系丰富：五行遁术、元神出窍、各式法宝（打神鞭、乾坤圈、阴阳镜等）。\n- 叙事风格：古典神魔小说气质，充满阵法斗法、天命因果、忠奸对抗。",
    },
    "sanguo": {
        "title": "三国风云",
        "description": "参考《三国演义》体系，在群雄割据、谋略纵横的汉末乱世中展开互动文字冒险。",
        "sourceUrl": None,
        "sourceText": "《三国演义》世界观摘要：\n- 时代背景：东汉末年，黄巾起义后群雄并起，魏蜀吴三分天下。\n- 核心主题：权谋、忠义、战争、治国、用人。\n- 关键阵营：魏（曹操）、蜀（刘备）、吴（孙权），以及周边势力如袁绍、吕布、刘表等。\n- 叙事风格：历史演义气质，注重谋略对话和战场描写，带浓厚的中原古风。",
    },
    "cyberpunk": {
        "title": "赛博边界",
        "description": "在霓虹与数据交错的反乌托邦未来都市中，扮演黑客、佣兵或社畜，揭开巨型企业的阴谋。",
        "sourceUrl": None,
        "sourceText": "赛博朋克世界观摘要：\n- 时代背景：近未来，巨型企业取代政府统治城市，AI 与义体改造普及。\n- 核心主题：身份认同、系统反抗、数据战争、街头生存。\n- 关键势力：荒坂集团（军事科技巨头）、网络行者（自由黑客集群）、义体医生黑市网络、底层街头帮派。\n- 叙事风格：冷硬 noir 气质，带赛博空间和物理世界的双重视角。",
    },
    "cthulhu": {
        "title": "克苏鲁低语",
        "description": "在 1920 年代阴郁小镇中调查不可名状的恐怖，理智与疯狂只在一线之间。",
        "sourceUrl": None,
        "sourceText": "克苏鲁神话世界观摘要：\n- 时代背景：1920 年代，美国新英格兰地区阿卡姆镇及周边。\n- 核心主题：未知恐惧、理智腐蚀、禁忌知识、不可名状的存在。\n- 关键元素：密斯卡塔尼克大学图书馆、印斯茅斯渔村、阿卡姆疯人院、上古邪物崇拜。\n- 叙事风格：洛夫克拉夫特式压抑氛围，线索导向的探索，理智值系统。",
    },
}

# ─── Blueprint helpers ────────────────────────────────────────────────────────

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
            {"name": "人间诸国", "goal": "在妖患、信仰和王权之间求安稳"},
        ],
        "locations": [
            {"name": "花果山", "keywords": ["花果山", "水帘洞", "灵猴"]},
            {"name": "长安城", "keywords": ["长安", "唐王", "人间"]},
            {"name": "流沙河", "keywords": ["流沙河", "弱水", "沙"]},
            {"name": "云栈洞", "keywords": ["云栈洞", "高老庄", "猪"]},
            {"name": "西天雷音", "keywords": ["西天", "灵山", "雷音"]},
        ],
        "mainQuests": [
            {"title": "开局入劫", "keywords": ["开局", "入劫", "身份"]},
            {"title": "取经路启", "keywords": ["取经", "西行", "长安"]},
            {"title": "洞府妖国", "keywords": ["妖国", "洞府", "妖王"]},
            {"title": "天庭名册", "keywords": ["天庭", "仙班", "名册"]},
            {"title": "灵山问心", "keywords": ["灵山", "雷音", "真经"]},
        ],
        "sideQuests": [
            {"title": "龙宫旧契", "keywords": ["龙宫", "龙王", "水族"]},
            {"title": "地府残页", "keywords": ["地府", "生死簿", "阎君"]},
            {"title": "凡国妖患", "keywords": ["国王", "城池", "妖患"]},
            {"title": "花果山余脉", "keywords": ["花果山", "猴群", "水帘洞"]},
        ],
        "identitySuggestions": [
            {"name": "取经路随行弟子", "description": "懂佛经皮毛，能记功过，也最容易被卷入劫难。"},
            {"name": "花果山新灵猴", "description": "身手轻快，熟悉妖族规矩，却未见过天庭真正威严。"},
            {"name": "天庭司簿小吏", "description": "掌一点名册文牒，知道神职漏洞，也背着天条压力。"},
            {"name": "龙宫巡海夜叉", "description": "通水脉、识宝器，在陆上行动却常受限制。"},
            {"name": "西牛贺洲散修", "description": "懂符箓与山野传闻，立场自由但根基不稳。"},
        ],
        "scenes": [
            {"label": "花果山水帘洞", "keywords": ["花果山", "水帘洞", "灵猴"], "prompt": "花果山水帘洞，瀑布如白练，石桥幽绿法光，群猴远望，东方神魔电影感背景"},
            {"label": "长安夜市", "keywords": ["长安", "人间", "唐王"], "prompt": "唐代长安夜色，灯火、经卷、官道与远处寺塔，暗色东方奇幻，适合作为文字冒险背景"},
            {"label": "洞府妖国", "keywords": ["妖国", "洞府", "妖王"], "prompt": "山腹洞府妖国，石殿、旌旗、幽火、妖王宝座，古典神魔小说氛围，高质量场景背景"},
            {"label": "灵山云路", "keywords": ["西天", "灵山", "雷音"], "prompt": "西天灵山云路，金色佛光被青绿云气包围，远处雷音寺若隐若现，电影感东方神话背景"},
        ],
        "gmPrompt": "",
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
5. A-D 选项只允许出现在回复最后四行，不要在叙事正文或状态栏中重复展示、解释或预告这些选项。
6. 选项格式严格使用：
A. 选项一
B. 选项二
C. 选项三
D. 选项四
7. 可以出现冲突、危机、斗法、追逐和辩论，但避免血腥细节和现实伤害指导。
8. 如果玩家要求结束、退出或谢幕，引导其使用结束按钮或总结当前旅程。"""


def complete_blueprint(blueprint):
    base = fallback_blueprint(blueprint.get("sourceTitle") or "西游记古文版")
    merged = {**base, **{k: v for k, v in blueprint.items() if v not in (None, "", [])}}
    for key in ["factions", "locations", "mainQuests", "sideQuests", "identitySuggestions", "scenes"]:
        if not isinstance(merged.get(key), list) or not merged[key]:
            merged[key] = base[key]
    if not merged.get("gmPrompt"):
        merged["gmPrompt"] = build_gm_prompt(merged)
    return merged


# ─── Game Save / Load ─────────────────────────────────────────────────────────

def _ensure_saves_dir():
    os.makedirs(SAVES_DIR, exist_ok=True)

def _save_game(data):
    _ensure_saves_dir()
    save_id = uuid.uuid4().hex[:12]
    path = os.path.join(SAVES_DIR, f"{save_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return save_id

def _load_game(save_id):
    # 安全：只允许 12 位 hex 字符的 save_id
    if not re.match(r"^[0-9a-f]{12}$", save_id):
        return None
    path = os.path.join(SAVES_DIR, f"{save_id}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ─── SSE helpers for streaming ───────────────────────────────────────────────

def _send_sse(wfile, event_type, data, ensure_ascii=False):
    """Write a single SSE data frame."""
    payload = json.dumps({"type": event_type, "content": data}, ensure_ascii=ensure_ascii)
    wfile.write(f"data: {payload}\n\n".encode("utf-8"))
    wfile.flush()


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class MyHandler(Handler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' https: data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "font-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        super().end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_headers(self):
        """Send SSE response headers."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        # No magic Content-Length — we're streaming
        self.end_headers()

    def _send_not_found(self, head_only=False):
        body = b"Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _read_json(self):
        raw_length = self.headers.get("Content-Length", "0")
        length = min(int(raw_length), MAX_REQUEST_SIZE) if raw_length else 0
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
        # Allow common frontend files at root level
        if requested_path:
            _, ext = os.path.splitext(requested_path.lower())
            if ext in {".css", ".js", ".html", ".json"}:
                return Handler.do_HEAD(self) if head_only else Handler.do_GET(self)
        requested_path = unquote(urlparse(self.path).path).lstrip("/")
        if requested_path and self._is_blocked_path(requested_path):
            return self._send_not_found(head_only=head_only)
        if requested_path and os.path.isfile(requested_path):
            if not self._is_public_asset(requested_path):
                return self._send_not_found(head_only=head_only)
            return Handler.do_HEAD(self) if head_only else Handler.do_GET(self)
        self.path = "/index.html"
        return Handler.do_HEAD(self) if head_only else Handler.do_GET(self)

    def _check_rate_limit(self):
        """Check rate limit for the current request. Returns True to proceed, False to 429."""
        client_key = _get_client_key(self)
        path = urlparse(self.path).path
        allowed = _check_ratelimit(client_key, path)
        if not allowed:
            self._send_json(429, {
                "message": "请求过于频繁，请稍后再试",
                "retry_after_seconds": 30,
            })
        return allowed

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/api/presets":
            presets_list = [
                {"id": kid, "title": v["title"], "description": v["description"], "sourceUrl": v.get("sourceUrl")}
                for kid, v in PRESETS.items()
            ]
            self._send_json(200, {"presets": presets_list})
            return
        if self.path == "/api/saves":
            _ensure_saves_dir()
            try:
                files = sorted(os.listdir(SAVES_DIR))[-20:]  # last 20
                saves = []
                for fn in files:
                    if fn.endswith(".json"):
                        fp = os.path.join(SAVES_DIR, fn)
                        with open(fp, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            saves.append({
                                "id": fn[:-5],
                                "title": meta.get("title", "未命名存档"),
                                "timestamp": os.path.getmtime(fp),
                            })
                self._send_json(200, {"saves": saves})
            except Exception as exc:
                self._send_json(200, {"saves": [], "message": str(exc)})
            return
        # /api/load/<id>
        if self.path.startswith("/api/load/"):
            save_id = self.path.split("/api/load/")[-1]
            data = _load_game(save_id)
            if data is None:
                self._send_json(404, {"message": "存档不存在"})
            else:
                self._send_json(200, {"save": data})
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
        # Rate-limit all API POST endpoints
        if self.path.startswith("/api/"):
            if not self._check_rate_limit():
                return
        if self.path == "/api/chat/stream":
            return self.handle_chat_stream()
        if self.path == "/api/chat":
            return self.handle_chat()
        if self.path == "/api/image":
            return self.handle_image()
        if self.path == "/api/generate-game":
            return self.handle_generate_game()
        if self.path == "/api/start-game":
            return self.handle_start_game()
        if self.path == "/api/save":
            return self.handle_save()
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

    # ── Streaming Chat (SSE) ──────────────────────────────────────────────

    def handle_chat_stream(self):
        """Streaming chat via Server-Sent Events.
        Calls DeepSeek with stream: true, forwards each content delta as SSE.
        """
        try:
            payload = self._read_json()
            api_key = os.environ.get("DEEPSEEK_API_KEY")

            self._send_sse_headers()

            if not api_key:
                fallback = self.fallback_chat(payload)
                _send_sse(self.wfile, "text", fallback)
                self._send_sse_done()
                return

            messages = payload.get("messages", [])
            deepseek_payload = {
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 1800,
                "stream": True,
            }

            data = json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8")
            req = request.Request(
                DEEPSEEK_URL,
                data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                method="POST",
            )

            full_content = ""
            with request.urlopen(req, timeout=90) as resp:
                while True:
                    line = resp.readline().decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            obj = json.loads(data_str)
                            delta = obj.get("choices", [{}])[0].get("delta", {})
                            # Skip empty role deltas
                            if delta.get("role"):
                                continue
                            content = delta.get("content", "")
                            if content:
                                full_content += content
                                _send_sse(self.wfile, "text", content, ensure_ascii=False)
                        except json.JSONDecodeError:
                            pass

            # Parse options from the full assembled content
            options = self._parse_options_from_text(full_content)
            if options:
                _send_sse(self.wfile, "options", options)

            self._send_sse_done()

        except Exception as exc:
            try:
                _send_sse(self.wfile, "error", str(exc))
                self._send_sse_done()
            except Exception:
                pass

    def _send_sse_done(self):
        """Send the [DONE] signal to end the SSE stream."""
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _parse_options_from_text(self, text):
        """Extract A-D options from a game master response text."""
        options = []
        for line in text.split("\n"):
            if re.match(r"^[A-D][.、．]\s+", line):
                opt_text = re.sub(r"^[A-D][.、．]\s*", "", line).strip()
                if opt_text:
                    options.append(opt_text)
        return options

    # ── Non-streaming Chat ────────────────────────────────────────────────

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

    # ── Game Generation (unchanged) ───────────────────────────────────────

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
gmPrompt 必须是完整系统提示词，要求主持人每轮 220-450 字，末尾包含状态栏和 A-D 四个选项，并明确 A-D 选项只出现在回复最后四行，不在叙事正文中重复。"""
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
要求：220-450 字；第三人称；NPC 对白用「」；末尾必须有状态栏和 A-D 四个选项。A-D 选项只放在回复最后四行，不要在正文中重复展示。
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

    # ── Image Generation (unchanged) ─────────────────────────────────────

    def handle_image(self):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            self._send_json(200, {"url": None, "skipped": True, "message": "缺少环境变量 DASHSCOPE_API_KEY"})
            return
        try:
            payload = self._read_json()
            scene = str(payload.get("scene") or "").strip()
            full_prompt = "高质量文字冒险场景背景，暗色东方奇幻，电影感，适合作为网页游戏背景，" + (
                scene or "古典神魔世界，幽绿法光，山水与云气"
            )
            # 缓存命中
            cached = _cache_get(full_prompt)
            if cached:
                self._send_json(200, {"url": cached, "cached": True})
                return
            create_payload = {
                "model": os.environ.get("DASHSCOPE_IMAGE_MODEL", "wanx2.0-t2i-turbo"),
                "input": {"prompt": full_prompt[:800]},
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
                _cache_set(full_prompt, results[0]["url"])
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
                        _cache_set(full_prompt, results[0]["url"])
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

    def handle_save(self):
        try:
            payload = self._read_json()
            save_data = {
                "title": payload.get("title", "未命名存档"),
                "blueprint": payload.get("blueprint"),
                "identity": payload.get("identity"),
                "history": payload.get("history", []),
                "progress": payload.get("progress", {}),
                "scene": payload.get("scene"),
                "timestamp": time.time(),
            }
            save_id = _save_game(save_data)
            self._send_json(200, {"saveId": save_id})
        except Exception as exc:
            self._send_json(500, {"message": f"存档失败: {exc}"})


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with ReusableTCPServer(("0.0.0.0", PORT), MyHandler) as httpd:
        print(f"AI 文字游戏生成器服务器启动 - 端口 {PORT}")
        httpd.serve_forever()
