# AI 文字游戏生成器

基于单页前端和 Python 标准库后端的 AI 文字游戏生成器。用户可以选择内置的 `西游记古文版` 预设，或输入自己的小说故事、世界观，系统会先生成游戏蓝图，再推荐身份并开局游玩。

内置预设参考公版《西游记》文本来源：<https://zh.wikisource.org/zh-hans/西游記>

## 本地运行

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
export DASHSCOPE_API_KEY="你的阿里云百炼 DashScope API Key"
python server.py
```

打开 `http://localhost:8080`。

如果没有配置 API Key，本地仍可用内置西游记蓝图兜底验证流程，但不会真正调用模型扩写，也不会生成背景图。场景图按当前剧情懒加载，并由后端缓存，避免在生成蓝图时批量预生成。

## 测试

```bash
python -m unittest discover -s tests
python -m py_compile server.py
```

## 环境变量

```bash
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DASHSCOPE_API_KEY=你的 DashScope API Key
DASHSCOPE_IMAGE_MODEL=wanx2.0-t2i-turbo
DASHSCOPE_IMAGE_SIZE=1024*1024
DASHSCOPE_POLL_INTERVAL=10
DASHSCOPE_MAX_POLLS=12
```

不要把 API Key 写入 `index.html` 或提交到 GitHub。

## Render 部署

1. 推送代码到 GitHub 仓库 `3105138391-sketch/ai_class_chatgame`。
2. 在 Render 创建 Web Service，选择 Docker runtime，或使用 `render.yaml`。
3. 配置 `DEEPSEEK_API_KEY` 与 `DASHSCOPE_API_KEY`。
4. 部署完成后访问 Render 提供的公网 URL。

## 安全说明

服务会阻止直接访问 `server.py`、`Dockerfile`、`render.yaml`、`.env*`、`.git/*` 等敏感路径。前端代码属于浏览器必须加载的内容，不能作为密钥或私有逻辑存放位置。
