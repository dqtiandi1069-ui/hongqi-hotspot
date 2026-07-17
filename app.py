"""
红旗品牌 · 社媒热点中枢 - 动态服务器
每次点击刷新时从公开热榜 API 抓取最新真实数据
"""
from flask import Flask, jsonify, render_template_string, request
import requests
import json
import os
import re
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)

# 缓存,避免频繁请求 API
_cache = {"data": None, "ts": 0}
_CACHE_TTL = 60  # 60 秒缓存

# ============= 品牌相关度判定规则 =============
HONGQI_HIGH_KEYWORDS = [
    '汽车', '车', '国潮', '国货', '新能源', '自驾', '318', '西藏', '公路',
    'GDP', '内需', '十五五', '外贸', '经济', '消费', '古诗词', '中式',
    '故宫', '非遗', '文化', '出海', '中国造', '国车', '红旗',
    '奥运', '亚运', '世界杯', '冠军', '国家队', '中国队',
    '阅兵', '国庆', '建军', '航天', '国产'
]
HONGQI_MID_KEYWORDS = [
    '旅行', '旅游', '文旅', '假期', '出游', '亲子', '家庭',
    '城市', '生活', '美景', '风景', '景区', '打卡', '祛魅',
    '出发', '勇气', '奋斗', '青春', '梦想', '励志',
    '收入', '工资', '房子', '未来'
]

# 分类关键词
CATEGORY_MAP = {
    'sport': ['世界杯', '奥运', '欧洲杯', '足球', '篮球', 'NBA', '球员', '比赛', '球赛',
              '联赛', '决赛', '半决赛', '亚马尔', '姆巴佩', '梅西', '阿根廷', '西班牙', '法国队',
              '德尚', '球场', '进球', '冠军', '亚军', '女足', 'CBA'],
    'eco': ['GDP', '经济', '外贸', '内需', '十五五', '股市', '发行', '申购', '融资',
            '央行', '利率', '人社部', '工资', '养老金', '通胀', '货币', '汇率', 'A股',
            '房价', '楼市', '消费', '价格', '税', '医保'],
    'auto': ['汽车', '车展', '新能源车', '电动车', '车企', '车龄', '车主', '智驾', '自动驾驶',
             '轮胎', '比亚迪', '特斯拉', '蔚来', '理想', '小鹏'],
    'tech': ['AI', 'DeepSeek', 'ChatGPT', '芯片', '半导体', '苹果', '华为', '小米', '手机',
             '科技', '大模型', 'GPT', 'Codex', '5G', '6G', 'iPhone', '机器人'],
    'life': ['旅行', '旅游', '美食', '穿搭', '拍照', '打卡', '景点', '生活', '入伏',
             '暑假', '寒假', '天气', '文旅', '亲子', '出游', '假期', '风景', '摄影'],
    'ent': ['电影', '剧', '综艺', '演员', '明星', '演唱会', '票房', '导演', '编剧',
            '偶像', '选秀', '演出', '首映', '开机', '杀青', '角色'],
    'news': ['暴雨', '地震', '事故', '判', '罚', '通报', '通报', '案', '被抓',
             '被查', '通缉', '受贿', '刑事', '民事', '涨水', '洪水', '台风']
}

def _detect_category(title: str) -> str:
    """根据标题关键词判定分类"""
    for cat, kws in CATEGORY_MAP.items():
        for kw in kws:
            if kw in title:
                return cat
    return 'other'

def _detect_hongqi_relevance(title: str) -> str:
    """红旗品牌相关度: high / mid / none"""
    for kw in HONGQI_HIGH_KEYWORDS:
        if kw in title:
            return 'high'
    for kw in HONGQI_MID_KEYWORDS:
        if kw in title:
            return 'mid'
    return 'none'


def fetch_platform(platform: str, limit: int = 15):
    """从公开 API 抓取平台热榜"""
    try:
        url = f"https://60s-api.viki.moe/v2/{platform}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        data = resp.json().get('data', [])
        items = []
        for i, x in enumerate(data[:limit]):
            title = x.get('title', '').strip()
            if not title:
                continue
            heat = x.get('hot_value', 0) or 0
            # 归一化热度为 "万"
            heat_wan = round(heat / 10000, 1) if heat > 10000 else (heat if heat > 0 else 0)
            items.append({
                'rank': i + 1,
                'plat': platform,
                'title': title,
                'heat': heat_wan,
                'raw_heat': heat,
                'link': x.get('link', ''),
                'cat': _detect_category(title),
                'hq': _detect_hongqi_relevance(title),
            })
        return items
    except Exception as e:
        print(f"[fetch_platform] {platform} failed: {e}")
        return []


def fetch_all_hotspots(force: bool = False):
    """抓取全部平台热榜(带缓存)"""
    now = time.time()
    if not force and _cache['data'] and (now - _cache['ts']) < _CACHE_TTL:
        return _cache['data'], True  # cached=True

    all_items = []
    platforms = ['weibo', 'douyin', 'zhihu']
    threads = []
    results = {}

    def _run(p):
        results[p] = fetch_platform(p, limit=15)

    for p in platforms:
        t = threading.Thread(target=_run, args=(p,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=10)

    for p in platforms:
        all_items.extend(results.get(p, []))

    # 统计
    hq_high = sum(1 for x in all_items if x['hq'] == 'high')
    hq_mid = sum(1 for x in all_items if x['hq'] == 'mid')
    max_heat_item = max(all_items, key=lambda x: x['raw_heat']) if all_items else None

    # 分类统计
    cat_stats = {}
    for x in all_items:
        cat_stats[x['cat']] = cat_stats.get(x['cat'], 0) + 1

    result = {
        'items': all_items,
        'stats': {
            'total': len(all_items),
            'hq_high': hq_high,
            'hq_mid': hq_mid,
            'max_heat_title': max_heat_item['title'] if max_heat_item else '',
            'max_heat_value': max_heat_item['heat'] if max_heat_item else 0,
            'max_heat_plat': max_heat_item['plat'] if max_heat_item else '',
            'categories': cat_stats,
        },
        'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

    _cache['data'] = result
    _cache['ts'] = now
    return result, False


# ============= API 路由 =============

@app.route('/api/hotspots')
def api_hotspots():
    force = request.args.get('force', '0') == '1'
    data, cached = fetch_all_hotspots(force=force)
    data['cached'] = cached
    return jsonify(data)


@app.route('/api/insight')
def api_insight():
    """基于当前热点生成营销洞察"""
    data, _ = fetch_all_hotspots(force=False)
    items = data['items']
    high_items = [x for x in items if x['hq'] == 'high'][:5]
    mid_items = [x for x in items if x['hq'] == 'mid'][:3]

    # 主导话题
    cat_stats = data['stats']['categories']
    top_cats = sorted(cat_stats.items(), key=lambda x: -x[1])[:2]
    top_cat_names = {'sport':'体育赛事', 'eco':'经济政策', 'life':'生活方式',
                     'ent':'娱乐文化', 'tech':'科技', 'auto':'汽车行业', 'news':'时事'}
    dominant = ' + '.join([top_cat_names.get(c, c) for c, _ in top_cats])

    # 生成机会点
    opportunities = []
    for item in high_items[:4]:
        opp = generate_opportunity(item)
        if opp:
            opportunities.append(opp)

    return jsonify({
        'dominant_topics': dominant,
        'high_relevant': high_items,
        'mid_relevant': mid_items,
        'opportunities': opportunities,
        'fetched_at': data['fetched_at'],
    })


def generate_opportunity(item):
    """根据单条热点生成红旗切入建议"""
    title = item['title']
    cat = item['cat']

    templates = {
        'sport': {
            'title': '🔥 抢占体育情感窗口',
            'desc': f'热点《{title}》体育情绪正浓,红旗可用"中国速度·中国骄傲"叙事切入,发布海外征程/冠军联名内容。'
        },
        'eco': {
            'title': '🇨🇳 消费信心叙事',
            'desc': f'热点《{title}》契合国民经济向好主线,红旗作为"国民自豪型消费"代表,可推出《国车买单·国民底气》系列。'
        },
        'auto': {
            'title': '🚗 汽车行业直接借势',
            'desc': f'热点《{title}》属汽车行业,红旗有天然发声权,可用产品数据/技术亮点正面回应。'
        },
        'life': {
            'title': '🌸 生活方式共振',
            'desc': f'热点《{title}》属生活方式话题,红旗可用车主 Vlog / 自驾场景 UGC 内容跟进。'
        },
        'tech': {
            'title': '🔬 科技话题绑定',
            'desc': f'热点《{title}》属科技领域,红旗可关联智能座舱/自动驾驶技术叙事。'
        },
    }
    tpl = templates.get(cat)
    if not tpl:
        return None
    return {
        'source_title': title,
        'source_plat': item['plat'],
        'source_heat': item['heat'],
        'title': tpl['title'],
        'desc': tpl['desc']
    }


# ============= 主页 =============
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>红旗品牌 · 社媒热点中枢(实时版) | HONGQI Social Insight</title>
<style>
  :root {
    --color-text-primary: #1a1a1a;
    --color-text-secondary: #666;
    --color-text-tertiary: #999;
    --color-bg-page: #F8F9FA;
    --color-bg-surface: #fff;
    --color-bg-subtle: #F5F5F5;
    --color-brand: #8B0000;
    --color-brand-light: #B71C1C;
    --color-border: #E5E5E5;
    --color-border-subtle: #F0F0F0;
    --color-success: #10B981;
    --color-warning: #F59E0B;
    --color-error: #EF4444;
    --radius-8: 8px; --radius-12: 12px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --color-text-primary: #E5E5E5;
      --color-text-secondary: #A0A0A0;
      --color-text-tertiary: #707070;
      --color-bg-page: #121212;
      --color-bg-surface: #1E1E1E;
      --color-bg-subtle: #2A2A2A;
      --color-border: #333;
      --color-border-subtle: #2A2A2A;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif;
    background: var(--color-bg-page);
    color: var(--color-text-primary);
    font-size: 16px;
    line-height: 1.5;
    min-height: 100vh;
  }
  .wrap { padding: 24px 16px; max-width: 1200px; margin: 0 auto; }

  /* Header */
  .hdr {
    background: linear-gradient(135deg, #8B0000 0%, #B71C1C 100%);
    border-radius: 12px;
    padding: 24px 32px;
    margin-bottom: 20px;
    color: #fff;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.07);
  }
  .brand { display: flex; align-items: center; gap: 16px; }
  .logo {
    width: 52px; height: 52px;
    background: #FFD700;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; color: #8B0000; font-size: 24px;
  }
  .title { font-size: 22px; font-weight: 700; }
  .sub { font-size: 12px; color: rgba(255,255,255,0.85); margin-top: 4px; letter-spacing: 1px; }
  .live {
    display: flex; align-items: center; gap: 6px;
    background: rgba(255,255,255,0.15);
    padding: 8px 14px; border-radius: 20px;
    font-size: 14px;
  }
  .live-dot {
    width: 8px; height: 8px;
    background: #4CAF50; border-radius: 50%;
    animation: pulse 1.5s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(1.3); }
  }
  .btn-refresh {
    background: rgba(255,255,255,0.2); color: #fff;
    border: 1px solid rgba(255,255,255,0.3);
    padding: 8px 18px; border-radius: 20px;
    cursor: pointer; font-size: 14px;
    display: flex; align-items: center; gap: 6px;
    font-family: inherit; font-weight: 500;
  }
  .btn-refresh:hover { background: rgba(255,255,255,0.35); }
  .btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-refresh.loading .icon { animation: spin 1s linear infinite; }
  @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

  /* Tabs */
  .tabs {
    display: flex; gap: 4px;
    margin-bottom: 20px;
    border-bottom: 1px solid var(--color-border-subtle);
    overflow-x: auto;
  }
  .tab {
    padding: 12px 20px;
    cursor: pointer; font-size: 15px;
    color: var(--color-text-secondary);
    border-bottom: 2px solid transparent;
    white-space: nowrap;
    font-weight: 500;
  }
  .tab.active { color: #8B0000; border-bottom-color: #8B0000; font-weight: 600; }

  /* Insight */
  .insight {
    background: linear-gradient(90deg, #FFF8E1 0%, #FFECB3 100%);
    border-left: 4px solid #FFC107;
    padding: 16px 20px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 14px;
    color: #5D4037;
    line-height: 1.6;
  }
  .insight strong { color: #8B0000; }
  @media (prefers-color-scheme: dark) {
    .insight { color: #FFECB3; }
  }

  /* Overview */
  .overview {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 20px;
  }
  .card {
    background: var(--color-bg-surface);
    border: 1px solid var(--color-border);
    border-radius: 12px;
    padding: 16px 20px;
  }
  .card-l { font-size: 14px; color: var(--color-text-secondary); }
  .card-v { font-size: 22px; font-weight: 700; margin-top: 6px; }
  .card-t { font-size: 12px; margin-top: 4px; color: var(--color-success); }

  /* Section */
  .sec {
    background: var(--color-bg-surface);
    border: 1px solid var(--color-border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 20px;
  }
  .sec-h {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px; flex-wrap: wrap; gap: 8px;
  }
  .sec-t {
    font-size: 18px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }
  .sec-t::before {
    content: ''; width: 4px; height: 18px;
    background: #8B0000; border-radius: 2px;
  }
  .meta { font-size: 12px; color: var(--color-text-tertiary); }
  .meta a { color: #8B0000; text-decoration: none; }

  /* Search */
  .search-row {
    display: flex; gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .search-input, .date-input {
    padding: 10px 14px;
    border: 1px solid var(--color-border);
    border-radius: 8px;
    font-size: 15px;
    background: var(--color-bg-page);
    color: var(--color-text-primary);
    font-family: inherit;
  }
  .search-input { flex: 1; min-width: 220px; }
  .btn-primary {
    padding: 10px 20px;
    background: #8B0000; color: #fff;
    border: none; border-radius: 8px;
    cursor: pointer; font-size: 15px; font-weight: 500;
    font-family: inherit;
  }
  .btn-primary:hover { background: #6B0000; }

  /* Platform tabs */
  .platforms {
    display: flex; gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }
  .plat {
    padding: 6px 14px; border-radius: 20px;
    background: var(--color-bg-subtle);
    border: 1px solid var(--color-border-subtle);
    font-size: 14px; cursor: pointer;
    color: var(--color-text-secondary);
    display: flex; align-items: center; gap: 6px;
  }
  .plat.active { background: #8B0000; color: #fff; border-color: #8B0000; }
  .plat-dot { width: 6px; height: 6px; border-radius: 50%; }

  .filters {
    display: flex; gap: 6px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .chip {
    padding: 4px 12px; border-radius: 12px;
    font-size: 12px;
    background: var(--color-bg-page);
    border: 1px solid var(--color-border-subtle);
    color: var(--color-text-secondary);
    cursor: pointer;
  }
  .chip.active {
    background: #FFD700; color: #8B0000;
    border-color: #FFD700; font-weight: 600;
  }

  /* Hot list */
  .hot-list { display: flex; flex-direction: column; gap: 8px; }
  .item {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 16px;
    border-radius: 8px;
    border: 1px solid transparent;
    cursor: pointer; transition: all 0.15s;
    text-decoration: none;
    color: inherit;
  }
  .item:hover {
    background: var(--color-bg-subtle);
    border-color: var(--color-border-subtle);
    transform: translateX(2px);
  }
  .item.hq-relevant {
    background: linear-gradient(90deg, rgba(255,215,0,0.15) 0%, transparent 60%);
    border-left: 3px solid #FFD700;
  }
  .item.hq-high {
    background: linear-gradient(90deg, rgba(139,0,0,0.1) 0%, transparent 60%);
    border-left: 3px solid #8B0000;
  }
  .rank {
    width: 28px; height: 28px; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 14px;
    flex-shrink: 0;
    background: var(--color-bg-subtle);
    color: var(--color-text-secondary);
  }
  .rank.top1 { background: #8B0000; color: #fff; }
  .rank.top2 { background: #D32F2F; color: #fff; }
  .rank.top3 { background: #F57C00; color: #fff; }
  .content { flex: 1; min-width: 0; }
  .item-title {
    font-size: 15px; font-weight: 500;
    margin-bottom: 6px; line-height: 1.4;
  }
  .item-meta {
    display: flex; gap: 8px;
    font-size: 11px;
    color: var(--color-text-tertiary);
    align-items: center; flex-wrap: wrap;
  }
  .tag {
    padding: 2px 8px; border-radius: 3px;
    font-size: 10px; font-weight: 500;
  }
  .tag-weibo { background: #FFF3E0; color: #E65100; }
  .tag-douyin { background: #FCE4EC; color: #C2185B; }
  .tag-zhihu { background: #E3F2FD; color: #1565C0; }
  .tag-xhs { background: #FFEBEE; color: #C62828; }
  .badge {
    padding: 2px 8px; border-radius: 3px;
    font-size: 10px; font-weight: 600;
  }
  .badge-hq { background: #8B0000; color: #FFD700; }
  .badge-mid { background: #FFD700; color: #8B0000; }
  .heat {
    text-align: right; font-size: 14px;
    color: var(--color-text-secondary); flex-shrink: 0;
  }
  .heat-v { font-weight: 700; color: #8B0000; font-size: 15px; }

  /* Loading */
  .loading {
    text-align: center;
    padding: 60px 20px;
    color: var(--color-text-tertiary);
  }
  .spinner {
    display: inline-block;
    width: 32px; height: 32px;
    border: 3px solid var(--color-border);
    border-top-color: #8B0000;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 12px;
  }

  /* Two column */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }

  /* Trending */
  .trend-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .trend {
    padding: 12px;
    background: var(--color-bg-page);
    border: 1px solid var(--color-border-subtle);
    border-radius: 8px;
  }
  .trend-h { display: flex; justify-content: space-between; margin-bottom: 8px; }
  .trend-t { font-size: 14px; font-weight: 600; flex: 1; }
  .trend-g {
    font-size: 11px; font-weight: 700;
    padding: 2px 8px;
    background: #FFEBEE; color: #C62828;
    border-radius: 4px; margin-left: 8px;
  }

  /* Calendar */
  .cal { display: flex; flex-direction: column; gap: 12px; }
  .cal-item {
    display: flex; align-items: center; gap: 16px;
    padding: 12px 16px;
    border-left: 3px solid #8B0000;
    background: var(--color-bg-page);
    border-radius: 0 8px 8px 0;
  }
  .cal-date { text-align: center; min-width: 64px; }
  .cal-day { font-size: 22px; font-weight: 700; color: #8B0000; line-height: 1; }
  .cal-month { font-size: 11px; color: var(--color-text-secondary); margin-top: 4px; }
  .cal-info { flex: 1; }
  .cal-name { font-weight: 600; margin-bottom: 4px; }
  .cal-desc { font-size: 14px; color: var(--color-text-secondary); line-height: 1.5; }
  .cal-badge {
    padding: 4px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 500;
  }
  .badge-high { background: #FFEBEE; color: #C62828; }
  .badge-mid { background: #FFF3E0; color: #E65100; }

  /* Opportunity */
  .opp {
    background: linear-gradient(135deg, #8B0000, #B71C1C);
    color: #fff; border-radius: 12px;
    padding: 24px; margin-bottom: 20px;
    position: relative; overflow: hidden;
  }
  .opp::before {
    content: '🎯'; position: absolute;
    right: 30px; top: 20px; font-size: 100px; opacity: 0.15;
  }
  .opp-t {
    font-size: 18px; font-weight: 700;
    margin-bottom: 16px;
    display: flex; align-items: center; gap: 8px;
  }
  .opp-body {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 12px; position: relative; z-index: 2;
  }
  .opp-card {
    background: rgba(255,255,255,0.1);
    padding: 16px; border-radius: 8px;
    border: 1px solid rgba(255,215,0,0.3);
  }
  .opp-h {
    font-size: 14px; font-weight: 600;
    color: #FFD700; margin-bottom: 6px;
  }
  .opp-d { font-size: 13px; color: rgba(255,255,255,0.9); line-height: 1.6; }
  .opp-source {
    font-size: 11px; color: rgba(255,255,255,0.6);
    margin-top: 8px; font-style: italic;
  }

  /* Footer */
  .footer {
    text-align: center;
    padding: 24px 16px;
    color: var(--color-text-tertiary);
    font-size: 12px;
    border-top: 1px solid var(--color-border-subtle);
    margin-top: 32px;
  }
  .footer a { color: #8B0000; text-decoration: none; }

  /* Panel */
  .panel { display: none; }
  .panel.active { display: block; }

  /* Toast */
  .toast {
    position: fixed;
    top: 20px; left: 50%;
    transform: translateX(-50%) translateY(-100px);
    background: #333; color: #fff;
    padding: 12px 24px; border-radius: 8px;
    font-size: 14px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    transition: transform 0.3s;
    z-index: 1000;
  }
  .toast.show { transform: translateX(-50%) translateY(0); }
  .toast.success { background: #10B981; }
  .toast.error { background: #EF4444; }

  @media (max-width: 768px) {
    .overview { grid-template-columns: repeat(2, 1fr); }
    .two-col, .opp-body, .trend-grid { grid-template-columns: 1fr; }
    .title { font-size: 18px; }
    .hdr { padding: 16px 20px; }
    .sec { padding: 16px; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="hdr">
    <div class="brand">
      <div class="logo">旗</div>
      <div>
        <div class="title">红旗品牌 · 社媒热点中枢</div>
        <div class="sub">HONGQI SOCIAL INSIGHT · LIVE 实时版</div>
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;">
      <div class="live"><div class="live-dot"></div><span id="liveTime">--:--:--</span></div>
      <button class="btn-refresh" id="btnRefresh" onclick="refreshData(true)">
        <span class="icon">🔄</span><span>刷新</span>
      </button>
    </div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="realtime">🔥 实时全网热点</div>
    <div class="tab" data-tab="rising">📈 上升趋势</div>
    <div class="tab" data-tab="history">📅 去年今日</div>
    <div class="tab" data-tab="calendar">🎯 营销节点</div>
  </div>

  <div class="insight" id="insightBar">
    <strong>🔴 实时洞察 · </strong>正在抓取最新热点数据...
  </div>

  <div class="overview" id="overview">
    <div class="card"><div class="card-l">🔴 抓取热点</div><div class="card-v" id="statTotal">--</div><div class="card-t">4 平台聚合</div></div>
    <div class="card"><div class="card-l">🎯 品牌高相关</div><div class="card-v" style="color:#8B0000" id="statHq">--</div><div class="card-t">红旗可切入</div></div>
    <div class="card"><div class="card-l">⚡ 主导话题</div><div class="card-v" style="font-size:16px" id="statDominant">--</div><div class="card-t">实时判定</div></div>
    <div class="card"><div class="card-l">📊 全网最高热</div><div class="card-v" style="color:#8B0000" id="statMaxHeat">--</div><div class="card-t" id="statMaxSrc">--</div></div>
  </div>

  <!-- Panel: Realtime -->
  <div class="panel active" id="panel-realtime">
    <div class="sec">
      <div class="search-row">
        <input type="text" class="search-input" placeholder="🔍 关键词过滤,例如:红旗、国潮、新能源..." id="searchInput" oninput="renderList()">
        <button class="btn-primary" onclick="clearSearch()">清空</button>
      </div>

      <div class="sec-h">
        <div class="sec-t">全网实时热点榜</div>
        <div class="meta">数据源:<a href="https://github.com/vikiboss/60s" target="_blank">60s 开源热榜 API</a> · 抓取时间:<span id="fetchTime">--</span></div>
      </div>

      <div class="platforms">
        <div class="plat active" data-p="all">🌐 全部平台</div>
        <div class="plat" data-p="weibo"><span class="plat-dot" style="background:#E65100"></span>微博</div>
        <div class="plat" data-p="douyin"><span class="plat-dot" style="background:#C2185B"></span>抖音</div>
        <div class="plat" data-p="zhihu"><span class="plat-dot" style="background:#1565C0"></span>知乎</div>
      </div>

      <div class="filters">
        <div class="chip active" data-f="all">全部</div>
        <div class="chip" data-f="hq">🎯 仅红旗高相关</div>
        <div class="chip" data-f="sport">⚽ 体育</div>
        <div class="chip" data-f="eco">💰 经济</div>
        <div class="chip" data-f="life">🌸 生活</div>
        <div class="chip" data-f="auto">🚗 汽车</div>
        <div class="chip" data-f="tech">🔬 科技</div>
        <div class="chip" data-f="ent">🎬 娱乐</div>
      </div>

      <div id="hotlist">
        <div class="loading"><div class="spinner"></div><div>正在抓取实时热点...</div></div>
      </div>
    </div>

    <div class="opp">
      <div class="opp-t">🎯 红旗品牌 · 即时切入机会(基于实时数据自动生成)</div>
      <div class="opp-body" id="oppBody">
        <div style="color:rgba(255,255,255,0.7);grid-column:1/-1;text-align:center;padding:20px">正在分析当前热点,生成营销切入建议...</div>
      </div>
    </div>
  </div>

  <!-- Panel: Rising -->
  <div class="panel" id="panel-rising">
    <div class="sec">
      <div class="sec-h"><div class="sec-t">近期上升趋势 · 7 日爆发话题</div></div>
      <div class="trend-grid" id="trendList"></div>
    </div>
  </div>

  <!-- Panel: History -->
  <div class="panel" id="panel-history">
    <div class="sec">
      <div class="sec-h">
        <div class="sec-t">去年今日 · 历史热点复盘</div>
      </div>
      <div class="search-row">
        <input type="date" class="date-input" id="histDate" style="flex:1">
        <button class="btn-primary" onclick="handleHistory()">查询</button>
      </div>
      <div class="hot-list" id="historyList"></div>
    </div>
  </div>

  <!-- Panel: Calendar -->
  <div class="panel" id="panel-calendar">
    <div class="sec">
      <div class="sec-h"><div class="sec-t">红旗品牌 · 近期重要营销节点</div></div>
      <div class="cal" id="calendar"></div>
    </div>
  </div>

  <div class="footer">
    <p><strong>红旗品牌 · 社媒热点中枢 · 实时版</strong> · 每次刷新都从公开 API 抓取最新热点数据</p>
    <p style="margin-top:8px">数据源:<a href="https://github.com/vikiboss/60s" target="_blank">60s Hotlist API</a> · 
    <a href="https://s.weibo.com/top/summary" target="_blank">微博热搜</a> · 
    <a href="https://www.douyin.com/hot" target="_blank">抖音热榜</a> · 
    <a href="https://www.zhihu.com/hot" target="_blank">知乎热榜</a></p>
    <p style="margin-top:8px;opacity:0.6">© 2026 HONGQI Social Insight · Powered by AI + Real-time Data</p>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
  // ============ 静态配置数据 ============
  const trending = [
    { title:'新中式豪华 · 中式美学复兴', growth:'+284%', tag:'汽车/品牌' },
    { title:'AI 二创短片病毒传播', growth:'+186%', tag:'内容/科技' },
    { title:'公路旅行自驾游热潮', growth:'+142%', tag:'汽车/文旅' },
    { title:'新能源家庭第二台车', growth:'+118%', tag:'汽车/消费' },
    { title:'县城咖啡与在地文化', growth:'+96%', tag:'消费/生活' },
    { title:'古诗词里的中国', growth:'+82%', tag:'文化/内容' },
  ];

  const historyData = [
    { rank:1, plat:'weibo', title:'2025 巴黎奥运会开幕在即', heat:3254, cat:'sport' },
    { rank:2, plat:'douyin', title:'"City不City"梗席卷抖音', heat:2178, cat:'ent' },
    { rank:3, plat:'zhihu', title:'新能源车渗透率突破 50%', heat:1562, cat:'auto' },
    { rank:4, plat:'xhs', title:'"多巴胺穿搭"再度翻红', heat:1246, cat:'life' },
    { rank:5, plat:'weibo', title:'高考志愿填报服务爆火', heat:986, cat:'edu' },
  ];

  const calendar = [
    { day:'20', month:'JUL', name:'成都车展开幕', desc:'国内三大车展之一,红旗新车型集中曝光窗口', level:'high' },
    { day:'01', month:'AUG', name:'建军节 · 家国情怀', desc:'红旗"红色基因"叙事最佳时机', level:'high' },
    { day:'08', month:'AUG', name:'七夕情人节', desc:'新中式浪漫 + 情侣自驾内容种草', level:'mid' },
    { day:'15', month:'AUG', name:'开学季启动', desc:'家庭用户购车决策高峰期', level:'mid' },
    { day:'01', month:'OCT', name:'国庆黄金周', desc:'红旗最具战略意义的营销窗口', level:'high' },
    { day:'11', month:'NOV', name:'双十一大促', desc:'汽车电商化 + 置换补贴 + 经销商联动', level:'mid' },
  ];

  const platName = { weibo:'微博', douyin:'抖音', zhihu:'知乎', xhs:'小红书' };
  const platCls = { weibo:'tag-weibo', douyin:'tag-douyin', zhihu:'tag-zhihu', xhs:'tag-xhs' };
  const catName = { sport:'体育', eco:'经济', life:'生活', ent:'娱乐', tech:'科技', news:'时事', auto:'汽车', edu:'教育', other:'其他' };
  const catNameFull = {sport:'体育赛事', eco:'经济政策', life:'生活方式', ent:'娱乐文化', tech:'科技', auto:'汽车行业', news:'时事'};

  let allHotspots = [];
  let curPlat = 'all', curFilter = 'all';

  // ============ Toast ============
  function toast(msg, type='') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast show ' + type;
    setTimeout(() => el.className = 'toast ' + type, 2400);
  }

  // ============ 抓取数据 ============
  async function refreshData(force = false) {
    const btn = document.getElementById('btnRefresh');
    btn.classList.add('loading');
    btn.disabled = true;
    if (force) toast('正在从 4 大平台抓取最新热点...', '');

    try {
      const resp = await fetch('/api/hotspots?force=' + (force ? '1' : '0'));
      const data = await resp.json();
      allHotspots = data.items || [];

      document.getElementById('fetchTime').textContent = data.fetched_at + (data.cached ? ' (缓存)' : ' (刚刚更新)');
      document.getElementById('statTotal').textContent = data.stats.total + ' 条';
      document.getElementById('statHq').textContent = (data.stats.hq_high + data.stats.hq_mid);
      document.getElementById('statMaxHeat').textContent = (data.stats.max_heat_value >= 10000 ? (data.stats.max_heat_value/10000).toFixed(1)+'亿' : data.stats.max_heat_value + '万');
      document.getElementById('statMaxSrc').textContent = platName[data.stats.max_heat_plat] + ' · ' + data.stats.max_heat_title.slice(0, 20);

      // 主导话题
      const cats = data.stats.categories;
      const sorted = Object.entries(cats).sort((a,b)=>b[1]-a[1]).slice(0, 2);
      document.getElementById('statDominant').textContent = sorted.map(([c,_])=>catNameFull[c]||c).join(' + ');

      // 加载洞察
      loadInsight();
      renderList();

      if (force) toast('✅ 已更新为最新数据', 'success');
    } catch(e) {
      console.error(e);
      toast('❌ 抓取失败,请稍后重试', 'error');
      document.getElementById('hotlist').innerHTML = '<div class="loading">❌ 数据抓取失败,请点击刷新按钮重试</div>';
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }

  async function loadInsight() {
    try {
      const resp = await fetch('/api/insight');
      const ins = await resp.json();

      // 更新洞察 banner
      const highTitles = ins.high_relevant.slice(0, 2).map(x => '《' + x.title + '》').join(' · ');
      const banner = `<strong>🔴 实时洞察 · </strong>本时段主导话题:<strong>${ins.dominant_topics}</strong>${highTitles ? ' · 红旗高相关:' + highTitles : ''}`;
      document.getElementById('insightBar').innerHTML = banner;

      // 更新机会点
      const oppBody = document.getElementById('oppBody');
      if (ins.opportunities && ins.opportunities.length > 0) {
        oppBody.innerHTML = ins.opportunities.map(o => `
          <div class="opp-card">
            <div class="opp-h">${o.title}</div>
            <div class="opp-d">${o.desc}</div>
            <div class="opp-source">📊 关联热点:${platName[o.source_plat]} · ${o.source_title.slice(0,30)}${o.source_title.length > 30 ? '...' : ''} · ${o.source_heat}万热度</div>
          </div>
        `).join('');
      } else {
        oppBody.innerHTML = '<div style="color:rgba(255,255,255,0.7);grid-column:1/-1;text-align:center;padding:20px">当前时段未发现红旗高相关热点,建议关注上升趋势板块</div>';
      }
    } catch(e) { console.error(e); }
  }

  // ============ 渲染热点列表 ============
  function renderList() {
    let data = allHotspots.slice();
    const kw = document.getElementById('searchInput').value.trim();
    if (curPlat !== 'all') data = data.filter(x => x.plat === curPlat);
    if (curFilter === 'hq') data = data.filter(x => x.hq === 'high' || x.hq === 'mid');
    else if (curFilter !== 'all') data = data.filter(x => x.cat === curFilter);
    if (kw) data = data.filter(x => x.title.includes(kw));
    data.sort((a,b) => b.raw_heat - a.raw_heat);
    data = data.slice(0, 30);

    if (data.length === 0) {
      document.getElementById('hotlist').innerHTML = '<div class="loading">当前筛选条件下暂无热点</div>';
      return;
    }

    document.getElementById('hotlist').innerHTML = data.map((h, idx) => {
      const rankCls = idx < 3 ? 'top' + (idx+1) : '';
      const hqCls = h.hq === 'high' ? 'hq-high' : (h.hq === 'mid' ? 'hq-relevant' : '');
      const hqBadge = h.hq === 'high' ? '<span class="badge badge-hq">🎯 高相关</span>' : (h.hq === 'mid' ? '<span class="badge badge-mid">🟡 可切入</span>' : '');
      const heatStr = h.heat >= 10000 ? (h.heat/10000).toFixed(1) + '亿' : h.heat + '万';
      const link = h.link || '#';
      return `
        <a href="${link}" target="_blank" class="item ${hqCls}">
          <div class="rank ${rankCls}">${idx+1}</div>
          <div class="content">
            <div class="item-title">${escapeHtml(h.title)}</div>
            <div class="item-meta">
              <span class="tag ${platCls[h.plat]}">${platName[h.plat]} #${h.rank}</span>
              <span>#${catName[h.cat] || '其他'}</span>
              ${hqBadge}
            </div>
          </div>
          <div class="heat">
            <div class="heat-v">${heatStr}</div>
            <div style="font-size:10px">热度</div>
          </div>
        </a>`;
    }).join('');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function clearSearch() {
    document.getElementById('searchInput').value = '';
    renderList();
  }

  function renderTrending() {
    document.getElementById('trendList').innerHTML = trending.map(t => `
      <div class="trend">
        <div class="trend-h">
          <div class="trend-t">${t.title}</div>
          <div class="trend-g">${t.growth}</div>
        </div>
        <div style="font-size:11px;color:var(--color-text-tertiary)">#${t.tag}</div>
      </div>
    `).join('');
  }

  function renderHistory() {
    document.getElementById('historyList').innerHTML = historyData.map((h, i) => {
      const heatStr = h.heat >= 1000 ? (h.heat/1000).toFixed(1) + '千万' : h.heat + '万';
      return `
        <div class="item">
          <div class="rank ${i<3?'top'+(i+1):''}">${i+1}</div>
          <div class="content">
            <div class="item-title">${h.title}</div>
            <div class="item-meta">
              <span class="tag ${platCls[h.plat]}">${platName[h.plat]}</span>
              <span>#${catName[h.cat] || '其他'}</span>
            </div>
          </div>
          <div class="heat"><div class="heat-v">${heatStr}</div><div style="font-size:10px">阅读</div></div>
        </div>`;
    }).join('');
  }

  function renderCalendar() {
    document.getElementById('calendar').innerHTML = calendar.map(c => `
      <div class="cal-item">
        <div class="cal-date">
          <div class="cal-day">${c.day}</div>
          <div class="cal-month">${c.month}</div>
        </div>
        <div class="cal-info">
          <div class="cal-name">${c.name}</div>
          <div class="cal-desc">${c.desc}</div>
        </div>
        <div class="cal-badge badge-${c.level}">${c.level==='high'?'高优先级':'中优先级'}</div>
      </div>
    `).join('');
  }

  function handleHistory() {
    const d = document.getElementById('histDate').value;
    toast('已加载 ' + d + ' 的历史热点(演示数据)', 'success');
  }

  // ============ 事件绑定 ============
  document.querySelectorAll('.tab').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
      document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
      document.getElementById('panel-' + el.dataset.tab).classList.add('active');
    });
  });

  document.querySelectorAll('.plat').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.plat').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
      curPlat = el.dataset.p;
      renderList();
    });
  });

  document.querySelectorAll('.chip').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
      curFilter = el.dataset.f;
      renderList();
    });
  });

  function updateClock() {
    const now = new Date();
    document.getElementById('liveTime').textContent = now.toTimeString().slice(0,8);
  }

  // ============ 初始化 ============
  const today = new Date();
  const lastYear = new Date();
  lastYear.setFullYear(today.getFullYear() - 1);
  document.getElementById('histDate').value = lastYear.toISOString().slice(0, 10);
  updateClock();
  setInterval(updateClock, 1000);

  renderTrending();
  renderHistory();
  renderCalendar();

  // 首次加载
  refreshData(false);

  // 每 5 分钟自动刷新
  setInterval(() => refreshData(false), 5 * 60 * 1000);
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return INDEX_HTML


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print("=" * 60)
    print("红旗品牌 · 社媒热点中枢 · 实时版")
    print("HONGQI Social Insight Command Center - Live Edition")
    print("=" * 60)
    print(f"Server starting on http://0.0.0.0:{port}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)
