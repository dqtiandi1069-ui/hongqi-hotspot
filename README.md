# 红旗品牌 · 社媒热点中枢(实时版)

> HONGQI Social Insight Command Center - Live Edition

一个为红旗品牌定制的社交媒体热点实时监测平台,聚合微博、抖音、知乎三大平台实时热榜,自动识别品牌高相关热点并生成营销切入建议。

## ✨ 核心功能

- 🔥 **实时热点抓取** — 每次刷新从公开 API 拉取最新热榜
- 🎯 **品牌相关度智能标注** — 自动识别红旗高相关/可切入热点
- 💡 **动态营销机会生成** — 根据当前热点分类生成红旗切入建议
- 📈 **上升趋势 / 去年今日 / 营销节点** — 完整决策支持
- 🌙 **暗色模式自适应** — 跟随系统主题
- 📱 **响应式设计** — PC / 平板 / 手机全适配

## 🚀 Railway 一键部署

### 方式一:通过 GitHub 部署(推荐)

1. **Fork 或上传本项目到您的 GitHub 仓库**
2. **登录 [Railway](https://railway.app/)**(可用 GitHub 账号免费注册)
3. 点击 **"New Project"** → **"Deploy from GitHub repo"**
4. 选择本仓库 → Railway 会自动检测配置并部署
5. 部署完成后,在 **Settings → Networking → Generate Domain** 生成公网域名

### 方式二:通过 Railway CLI 部署

```bash
# 1. 安装 Railway CLI
npm install -g @railway/cli

# 2. 登录
railway login

# 3. 在项目目录初始化
cd hongqi_railway
railway init

# 4. 部署
railway up

# 5. 生成公网域名
railway domain
```

## 📁 项目结构

```
hongqi_railway/
├── app.py              # Flask 主服务器(含前端页面)
├── requirements.txt    # Python 依赖
├── Procfile            # Railway 启动配置
├── railway.json        # Railway 配置文件
├── runtime.txt         # Python 版本
├── .gitignore
└── README.md
```

## 🔧 本地运行

```bash
pip install -r requirements.txt
python app.py
# 访问 http://localhost:8080
```

## 💰 Railway 免费额度说明

Railway 提供每月 **$5 免费额度**(约 500 小时运行时间),对于本应用完全足够:
- 单实例应用,内存占用 < 100MB
- 无数据库依赖,零运行成本
- 支持自动休眠(无访问时不计费)

## 📊 数据源

- 微博热搜、抖音热榜、知乎热榜 - 通过 [60s 开源 API](https://github.com/vikiboss/60s)
- 数据每 60 秒缓存,避免频繁请求
- 前端每 5 分钟自动刷新

## 📄 License

MIT · 2026 HONGQI Social Insight
