#!/usr/bin/env python3
"""QA 排期看板刷新脚本 — 从 TAPD 拉取并推送到 GitHub Pages。

功能：
1. 拉取 4 个已收录分类的 QA 组需求 → 生成看板 HTML → 推送 GitHub
2. 漏需求检测：扫描全项目其他分类，找出 QA 组负责但未收录的需求

运行方式：
- 本地：python3 refresh_qa_schedule.py（PAT 从 ~/AppData/Local/hermes/config.yaml 读取）
- GitHub Actions：需要环境变量 TAPD_TOKEN + GH_PAT（在仓库 Secrets 配置）
"""
import requests, json, base64, os, re
from collections import Counter, defaultdict
from datetime import datetime

# ═══ 配置 ═══
TAPD_WS = "21711231"
GH_OWNER = "buxiuduwu1"
GH_REPO = "qa-schedule"
GH_PATH = "index.html"

# 环境变量优先（云端），否则用内置/本地配置
TAPD_TOKEN = os.environ.get("TAPD_TOKEN", "c7d76bfae20c89cd98246ea02886a46413f07f20")

QA_TEAM = {
    '吴淦淦', '李研锋', '张家像', '周旋之', '杨钦', '张海志', '吕昕远',
    '刘政豪', '张秋涵', '卢谦', '夏绍昌', '欧阳福辉', '刘鹏鸣', '李子涵'
}

# 已收录分类（看板展示）
CATEGORY_IDS = [
    ('1121711231001000206', '项目测试'),
    ('1121711231001000434', '任务玩法'),
    ('1121711231001000180', '数值系统'),
    ('1121711231001000871', '小型团本07-幽姬'),
]
INCLUDED_CAT_IDS = {cid for cid, _ in CATEGORY_IDS}

# 明确排除的分类（即使 QA 负责也不算漏网，用户确认）
EXCLUDED_CAT_IDS = {
    '1121711231001000762': '测试说明文档',
    '1121711231001000301': '用例设计',
    '1121711231001000553': '项目支持内部工作',
    '1121711231001000544': '自动化测试',
    '1121711231001000192': 'QA内部工作',
}

STATUS_MAP = {
    'new': '新', 'status_17': '设计取消', 'status_11': '已提测',
    'status_7': '测试中', 'suspended': '挂起'
}
STATUS_ORDER = ['新', '设计取消', '已提测', '测试中', '挂起']


def get_headers():
    return {"Authorization": f"Bearer {TAPD_TOKEN}", "User-Agent": "Mozilla/5.0"}


def get_pat():
    """GitHub PAT：环境变量优先（云端），本地回退到 config.yaml"""
    env_pat = os.environ.get("GH_PAT", "").strip()
    if env_pat:
        return env_pat
    config_path = os.path.expanduser("~/AppData/Local/hermes/config.yaml")
    with open(config_path) as f:
        raw = f.read()
    match = re.search(r'(ghp_[A-Za-z0-9]{30,})', raw)
    if not match:
        raise RuntimeError("GitHub PAT not found (env GH_PAT or config.yaml)")
    return match.group(1)


def fetch_stories():
    """拉取 4 个已收录分类的 QA 组需求"""
    headers = get_headers()
    base_url = "https://api.tapd.cn"
    all_stories = []

    for cid, cname in CATEGORY_IDS:
        page = 1
        while True:
            resp = requests.get(f"{base_url}/stories", headers=headers, params={
                'workspace_id': TAPD_WS, 'category_id': cid,
                'limit': '200', 'page': str(page),
                'fields': 'id,name,status,developer,owner,created'
            })
            data = resp.json().get('data', [])
            if not data:
                break
            for item in data:
                s = item['Story']
                if s.get('status') == 'resolved':
                    continue
                dev_raw = s.get('developer', '') or ''
                devs = set(d.strip() for d in dev_raw.split(';') if d.strip())
                if devs & QA_TEAM:
                    main_dev = next((d for d in dev_raw.split(';') if d.strip() in QA_TEAM), '')
                    st = STATUS_MAP.get(s['status'], s['status'])
                    all_stories.append({
                        'name': main_dev, 'title': s['name'], 'status': st,
                        'status_raw': s['status'], 'owner': s.get('owner', ''),
                        'created': s.get('created', '')[:10],
                        'url': f"https://www.tapd.cn/{TAPD_WS}/prong/stories/view/{s['id']}"
                    })
            if len(data) < 200:
                break
            page += 1

    print(f"Fetched {len(all_stories)} stories from {len(CATEGORY_IDS)} included categories")
    return all_stories


def fetch_leaked_stories():
    """漏需求检测：扫描已收录 + 已排除之外的其他分类，找出 QA 组负责的需求"""
    headers = get_headers()
    base_url = "https://api.tapd.cn"

    # 1. 获取全部分类
    resp = requests.get(f"{base_url}/story_categories", headers=headers,
                        params={'workspace_id': TAPD_WS, 'limit': '200'})
    categories = {}
    for item in resp.json().get('data', []):
        c = item['Category']
        categories[str(c['id'])] = c['name']

    # 2. 确定要扫描的分类 = 全部 - 已收录 - 已排除
    scan_ids = [cid for cid in categories
                if cid not in INCLUDED_CAT_IDS and cid not in EXCLUDED_CAT_IDS]

    # 3. 逐个分类拉取，过滤 QA 组 + 非 resolved
    leaked = []
    for cid in scan_ids:
        page = 1
        while True:
            resp = requests.get(f"{base_url}/stories", headers=headers, params={
                'workspace_id': TAPD_WS, 'category_id': cid,
                'limit': '200', 'page': str(page),
                'fields': 'id,name,status,developer,owner,created'
            })
            data = resp.json().get('data', [])
            if not data:
                break
            for item in data:
                s = item['Story']
                if s.get('status') == 'resolved':
                    continue
                dev_raw = s.get('developer', '') or ''
                devs = set(d.strip() for d in dev_raw.split(';') if d.strip())
                if devs & QA_TEAM:
                    main_dev = next((d for d in dev_raw.split(';') if d.strip() in QA_TEAM), '')
                    st = STATUS_MAP.get(s['status'], s['status'])
                    leaked.append({
                        'name': main_dev, 'title': s['name'], 'status': st,
                        'status_raw': s['status'], 'owner': s.get('owner', ''),
                        'created': s.get('created', '')[:10],
                        'category': categories.get(cid, cid),
                        'url': f"https://www.tapd.cn/{TAPD_WS}/prong/stories/view/{s['id']}"
                    })
            if len(data) < 200:
                break
            page += 1

    print(f"Leaked scan: {len(scan_ids)} categories scanned, {len(leaked)} leaked stories")
    return leaked


def build_data(all_stories):
    dev_groups = defaultdict(list)
    for s in all_stories:
        dev_groups[s['name']].append(s)
    dev_order = sorted(dev_groups.items(), key=lambda x: (-len(x[1]), x[0]))

    data_json, dev_rows, summary, inactive = [], [], Counter(), []
    for dev_name, items in dev_order:
        items_sorted = sorted(items, key=lambda x: (
            STATUS_ORDER.index(x['status']) if x['status'] in STATUS_ORDER else 99,
            x['created']), reverse=False)
        stats = Counter(i['status'] for i in items_sorted)
        for st, n in stats.items():
            summary[st] += n
        summary['total'] += len(items_sorted)
        dev_rows.append({
            'name': dev_name, 'total': len(items_sorted),
            '新': stats.get('新',0), '设计取消': stats.get('设计取消',0),
            '已提测': stats.get('已提测',0), '测试中': stats.get('测试中',0),
            '挂起': stats.get('挂起',0)
        })
        data_json.append({
            'name': dev_name, 'total': len(items_sorted),
            'summary': ' '.join(f'{st}{stats.get(st,0)}' for st in STATUS_ORDER if stats.get(st,0)),
            'stats': {st: stats.get(st,0) for st in STATUS_ORDER},
            'stories': [{'idx': i+1, 'name': s['title'], 'status': s['status_raw'],
                         'status_cn': s['status'], 'owner': s['owner'],
                         'created': s['created'], 'id': s['url'].split('/')[-1]}
                        for i, s in enumerate(items_sorted)]
        })

    for name in QA_TEAM:
        if name not in dev_groups:
            inactive.append(name)

    return data_json, dev_rows, summary, inactive


def build_leaked_data(leaked):
    """漏需求分组：按分类 → 人员 → 需求"""
    by_cat = defaultdict(list)
    for s in leaked:
        by_cat[s['category']].append(s)

    cat_list = []
    total = 0
    for cat_name in sorted(by_cat.keys()):
        items = by_cat[cat_name]
        total += len(items)
        devs = Counter(i['name'] for i in items)
        cat_list.append({
            'category': cat_name,
            'total': len(items),
            'devs': dict(devs),
            'stories': [{'idx': i+1, 'name': s['title'], 'status': s['status'],
                         'dev': s['name'], 'created': s['created'],
                         'id': s['url'].split('/')[-1]} for i, s in enumerate(items)]
        })
    return cat_list, total


def generate_html(data_json, dev_rows, summary, inactive, leaked_cats, leaked_total, now_str):
    DATA_STR = json.dumps(data_json, ensure_ascii=False)
    SUMMARY_STR = json.dumps(dict(summary), ensure_ascii=False)
    DEVROWS_STR = json.dumps(dev_rows, ensure_ascii=False)
    INACTIVE_STR = json.dumps(inactive, ensure_ascii=False)
    LEAKED_STR = json.dumps(leaked_cats, ensure_ascii=False)
    inactive_text = '; '.join(inactive) if inactive else '（无）'

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QA 排期看板 · 诛仙世界</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#111827; color:#e5e7eb; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; padding:20px; max-width:1200px; margin:0 auto; }}
.header {{ text-align:center; padding:20px 0 10px; }}
.header h1 {{ font-size:24px; color:#f9fafb; }}
.header .sub {{ font-size:13px; color:#9ca3af; margin-top:4px; }}
.header .refresh {{ font-size:12px; color:#6b7280; margin-top:2px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:16px 0; }}
.card {{ background:#1f2937; border-radius:10px; padding:16px; text-align:center; border-left:4px solid #374151; }}
.card .num {{ font-size:28px; font-weight:700; }}
.card .label {{ font-size:13px; color:#9ca3af; margin-top:4px; }}
.card-new {{ border-left-color:#FF6770; }} .card-new .num {{ color:#FF6770; }}
.card-cancelled {{ border-left-color:#FAA23B; }} .card-cancelled .num {{ color:#FAA23B; }}
.card-submitted {{ border-left-color:#70B400; }} .card-submitted .num {{ color:#70B400; }}
.card-testing {{ border-left-color:#0D68FF; }} .card-testing .num {{ color:#0D68FF; }}
.card-suspended {{ border-left-color:#9CA3AF; }} .card-suspended .num {{ color:#9CA3AF; }}
.card-total {{ border-left-color:#8b5cf6; }} .card-total .num {{ color:#8b5cf6; }}
.card-leaked {{ border-left-color:#f59e0b; }} .card-leaked .num {{ color:#f59e0b; }}
.table-wrap {{ overflow-x:auto; margin:20px 0; background:#1f2937; border-radius:10px; padding:4px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ background:#374151; color:#d1d5db; font-weight:600; padding:10px 12px; text-align:left; white-space:nowrap; }}
td {{ padding:8px 12px; border-bottom:1px solid #374151; }}
tr:hover td {{ background:#283548; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:700; color:#fff; min-width:28px; text-align:center; }}
.badge-new {{ background:#FF6770; }} .badge-cancelled {{ background:#FAA23B; }}
.badge-submitted {{ background:#70B400; }} .badge-testing {{ background:#0D68FF; }}
.badge-suspended {{ background:#9CA3AF; }}
.row-hot {{ background:#7f1d1d22; }} .row-warm {{ background:#78350f22; }}
.toolbar {{ display:flex; flex-wrap:wrap; gap:10px; margin:16px 0; align-items:center; }}
.toolbar input {{ flex:1; min-width:200px; padding:8px 14px; background:#1f2937; border:1px solid #374151; border-radius:8px; color:#e5e7eb; font-size:14px; outline:none; }}
.toolbar input:focus {{ border-color:#8b5cf6; }}
.filter-btns {{ display:flex; gap:6px; flex-wrap:wrap; }}
.fbtn {{ padding:6px 14px; border-radius:8px; border:1px solid #374151; background:#1f2937; color:#9ca3af; cursor:pointer; font-size:13px; transition:all .2s; }}
.fbtn:hover {{ background:#374151; }}
.fbtn.active {{ background:#8b5cf6; border-color:#8b5cf6; color:#fff; }}
.toggle-all {{ padding:6px 14px; border-radius:8px; border:1px solid #374151; background:#1f2937; color:#9ca3af; cursor:pointer; font-size:13px; }}
.toggle-all:hover {{ background:#374151; }}
.accordion {{ margin:16px 0; }}
.acc-group {{ margin-bottom:12px; background:#1f2937; border-radius:10px; overflow:hidden; }}
.acc-header {{ padding:12px 16px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; border-left:4px solid #374151; transition:background .2s; }}
.acc-header:hover {{ background:#283548; }}
.acc-header h3 {{ font-size:15px; color:#f3f4f6; }}
.acc-header .acc-total {{ font-size:13px; color:#9ca3af; }}
.acc-header .acc-badges {{ display:flex; gap:4px; margin-left:auto; margin-right:12px; }}
.acc-arrow {{ transition:transform .3s; font-size:12px; color:#6b7280; }}
.acc-group.open .acc-arrow {{ transform:rotate(90deg); }}
.acc-body {{ display:none; padding:0 16px 12px; }}
.acc-group.open .acc-body {{ display:block; }}
.acc-item {{ display:flex; align-items:center; padding:6px 0; border-bottom:1px solid #1f2937; font-size:13px; gap:8px; }}
.acc-item:last-child {{ border-bottom:none; }}
.acc-item .st-tag {{ flex-shrink:0; padding:2px 10px; border-radius:10px; font-size:11px; font-weight:700; color:#fff; }}
.acc-item .st-link {{ flex:1; color:#93c5fd; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.acc-item .st-link:hover {{ text-decoration:underline; }}
.acc-item .st-meta {{ flex-shrink:0; color:#6b7280; font-size:11px; }}
.tag-new {{ background:#FF6770; }} .tag-cancelled {{ background:#FAA23B; }}
.tag-submitted {{ background:#70B400; }} .tag-testing {{ background:#0D68FF; }}
.tag-suspended {{ background:#9CA3AF; }}
.leaked {{ margin:16px 0; background:#1a1608; border:1px solid #f59e0b55; border-radius:10px; overflow:hidden; }}
.leaked-header {{ padding:12px 16px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; border-left:4px solid #f59e0b; }}
.leaked-header:hover {{ background:#221c0c; }}
.leaked-header h3 {{ font-size:15px; color:#fbbf24; }}
.leaked-header .acc-total {{ font-size:13px; color:#d97706; }}
.leaked-body {{ display:none; padding:0 16px 12px; }}
.leaked.open .leaked-body {{ display:block; }}
.leaked-cat {{ margin:10px 0; padding:8px 12px; background:#221c0c; border-radius:8px; }}
.leaked-cat .cat-title {{ font-size:13px; font-weight:700; color:#fbbf24; margin-bottom:6px; }}
.footer {{ text-align:center; padding:20px 0; color:#4b5563; font-size:12px; }}
@media (max-width:640px) {{
  body {{ padding:10px; }}
  .header h1 {{ font-size:18px; }}
  .cards {{ grid-template-columns:repeat(3,1fr); gap:8px; }}
  .card {{ padding:10px; }}
  .card .num {{ font-size:22px; }}
  .acc-item {{ flex-wrap:wrap; }}
}}
.hidden {{ display:none !important; }}
.no-results {{ text-align:center; padding:40px; color:#6b7280; }}
</style>
</head>
<body>
<div class="header">
  <h1>🔧 QA 测试需求排期看板</h1>
  <div class="sub">诛仙世界 · 项目测试 / 任务玩法 / 数值系统 / 小型团本07-幽姬</div>
  <div class="refresh">📅 数据更新于 {now_str} · 共 {summary['total']} 条需求</div>
</div>
<div class="cards">
  <div class="card card-total"><div class="num">{summary['total']}</div><div class="label">📋 合计</div></div>
  <div class="card card-new"><div class="num">{summary.get('新',0)}</div><div class="label">🆕 新</div></div>
  <div class="card card-cancelled"><div class="num">{summary.get('设计取消',0)}</div><div class="label">🚫 设计取消</div></div>
  <div class="card card-submitted"><div class="num">{summary.get('已提测',0)}</div><div class="label">✅ 已提测</div></div>
  <div class="card card-testing"><div class="num">{summary.get('测试中',0)}</div><div class="label">🔬 测试中</div></div>
  <div class="card card-suspended"><div class="num">{summary.get('挂起',0)}</div><div class="label">⏸ 挂起</div></div>
  <div class="card card-leaked"><div class="num">{leaked_total}</div><div class="label">⚠ 分类外</div></div>
</div>
<div class="table-wrap">
  <table>
    <thead>
      <tr><th>开发人员</th><th>合计</th><th>新</th><th>设计取消</th><th>已提测</th><th>测试中</th><th>挂起</th></tr>
    </thead>
    <tbody id="summaryBody"></tbody>
  </table>
</div>
<div style="font-size:12px;color:#6b7280;margin-top:-12px;margin-bottom:8px;padding-left:4px;">无活跃需求：{inactive_text}</div>
<div class="toolbar">
  <input type="text" id="search" placeholder="🔍 搜索需求标题..." oninput="filterAll()"/>
  <div class="filter-btns">
    <button class="fbtn active" onclick="toggleFilter(this,'all')">全部</button>
    <button class="fbtn" onclick="toggleFilter(this,'新')" style="border-color:#FF6770;color:#FF6770;">新</button>
    <button class="fbtn" onclick="toggleFilter(this,'设计取消')" style="border-color:#FAA23B;color:#FAA23B;">设计取消</button>
    <button class="fbtn" onclick="toggleFilter(this,'已提测')" style="border-color:#70B400;color:#70B400;">已提测</button>
    <button class="fbtn" onclick="toggleFilter(this,'测试中')" style="border-color:#0D68FF;color:#0D68FF;">测试中</button>
    <button class="fbtn" onclick="toggleFilter(this,'挂起')" style="border-color:#9CA3AF;color:#9CA3AF;">挂起</button>
  </div>
  <button class="toggle-all" onclick="toggleAll()">📂 展开全部</button>
</div>
<div class="accordion" id="accordion"></div>
<div class="no-results hidden" id="noResults">😕 无匹配结果</div>
<div class="leaked" id="leakedBox">
  <div class="leaked-header" onclick="this.parentElement.classList.toggle('open')">
    <h3>⚠ 分类外需求检测</h3>
    <span class="acc-total">{leaked_total} 条 · 点击展开</span>
    <span class="acc-arrow">▶</span>
  </div>
  <div class="leaked-body" id="leakedBody"></div>
</div>
<div class="footer">数据来源：TAPD API · 诛仙世界 workspace 21711231 · 每周一 12:00 自动刷新 · GitHub Actions 云端执行</div>
<script>
const DATA = {DATA_STR};
const SUMMARY = {SUMMARY_STR};
const DEVROWS = {DEVROWS_STR};
const INACTIVE = {INACTIVE_STR};
const LEAKED = {LEAKED_STR};
const STATUS_ORDER = ['新','设计取消','已提测','测试中','挂起'];
const TAG_CLASS = {{'新':'tag-new','设计取消':'tag-cancelled','已提测':'tag-submitted','测试中':'tag-testing','挂起':'tag-suspended'}};
const BADGE_CLASS = {{'新':'badge-new','设计取消':'badge-cancelled','已提测':'badge-submitted','测试中':'badge-testing','挂起':'badge-suspended'}};
let activeFilter = 'all';
function renderSummary() {{
  document.getElementById('summaryBody').innerHTML = DEVROWS.map(d => {{
    let rc = d.total >= 10 ? 'row-hot' : d.total >= 7 ? 'row-warm' : '';
    let bd = STATUS_ORDER.map(st => {{ let n = d[st]||0; return n ? '<td><span class="badge '+BADGE_CLASS[st]+'">'+n+'</span></td>' : '<td></td>'; }}).join('');
    return '<tr class="'+rc+'"><td><strong>'+d.name+'</strong></td><td><strong>'+d.total+'</strong></td>'+bd+'</tr>';
  }}).join('');
}}
function renderAccordion() {{
  let c = document.getElementById('accordion'), s = document.getElementById('search').value.toLowerCase(), h = '';
  DATA.forEach(g => {{
    let f = g.items.filter(i => {{ return (!s||i.title.toLowerCase().includes(s)) && (activeFilter==='all'||i.status===activeFilter); }});
    if(!f.length && activeFilter!=='all') return;
    let sb = STATUS_ORDER.map(st => {{ let n=g.stats[st]||0; return n?'<span class="badge '+BADGE_CLASS[st]+'" style="font-size:11px;">'+n+'</span>':''; }}).filter(Boolean).join('');
    h += '<div class="acc-group" data-dev="'+g.name+'"><div class="acc-header" onclick="toggleAccordion(this)"><h3>'+g.name+'</h3><div class="acc-badges">'+sb+'</div><span class="acc-total">'+g.total+'条</span><span class="acc-arrow">▶</span></div><div class="acc-body">'+f.map(i => '<div class="acc-item"><span class="st-tag '+TAG_CLASS[i.status]+'">'+i.status+'</span><a class="st-link" href="'+i.url+'" target="_blank" title="'+i.title.replace(/"/g,'&quot;')+'">'+i.title+'</a><span class="st-meta">'+i.created+'</span></div>').join('')+'</div></div>';
  }});
  c.innerHTML = h;
  document.getElementById('noResults').classList.toggle('hidden', !!c.innerHTML.trim());
}}
function renderLeaked() {{
  let box = document.getElementById('leakedBody');
  if (!LEAKED || LEAKED.length === 0) {{
    box.innerHTML = '<div style="padding:12px;color:#6b7280;font-size:13px;">✅ 未发现分类外的 QA 需求</div>';
    return;
  }}
  box.innerHTML = LEAKED.map(cat => {{
    let devs = Object.entries(cat.devs).map(([d,n]) => '<span style="display:inline-block;background:#374151;border-radius:10px;padding:1px 8px;font-size:11px;margin:2px;">'+d+'×'+n+'</span>').join(' ');
    let rows = cat.stories.map(s => '<div class="acc-item"><span class="st-tag '+TAG_CLASS[s.status]+'">'+s.status+'</span><a class="st-link" href="'+TAPD_URL_STR+s.id+'" target="_blank">'+s.name+'</a><span class="st-meta">'+s.dev+' · '+s.created+'</span></div>').join('');
    return '<div class="leaked-cat"><div class="cat-title">'+cat.category+'（'+cat.total+'条） '+devs+'</div>'+rows+'</div>';
  }}).join('');
}}
const TAPD_URL_STR = 'https://www.tapd.cn/{TAPD_WS}/prong/stories/view/';
function toggleAccordion(h) {{ h.parentElement.classList.toggle('open'); }}
function toggleFilter(b,st) {{ document.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('active')); b.classList.add('active'); activeFilter=st; filterAll(); }}
function filterAll() {{ renderAccordion(); }}
function toggleAll() {{ let gs=document.querySelectorAll('.acc-group'), ao=Array.from(gs).every(g=>g.classList.contains('open')); gs.forEach(g=>g.classList.toggle('open',!ao)); document.querySelector('.toggle-all').textContent=ao?'📂 展开全部':'📁 折叠全部'; }}
renderSummary(); renderAccordion(); renderLeaked();
</script>
</body>
</html>'''


def push_to_github(html, pat):
    owner, repo, path = GH_OWNER, GH_REPO, GH_PATH
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github.v3+json"}

    resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
    sha = resp.json().get('sha') if resp.status_code == 200 else None

    content_b64 = base64.b64encode(html.encode('utf-8')).decode('utf-8')
    payload = {"message": "QA排期看板自动刷新", "content": content_b64, "branch": "main"}
    if sha:
        payload["sha"] = sha

    resp = requests.put(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                        headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub push failed: {resp.status_code} {resp.json()}")
    return resp.json()['commit']['sha']


def main():
    pat = get_pat()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    stories = fetch_stories()
    data_json, dev_rows, summary, inactive = build_data(stories)

    leaked = fetch_leaked_stories()
    leaked_cats, leaked_total = build_leaked_data(leaked)

    html = generate_html(data_json, dev_rows, summary, inactive, leaked_cats, leaked_total, now_str)
    commit_sha = push_to_github(html, pat)

    print(f"✅ 看板已刷新 · 收录{summary['total']}条 · 分类外{leaked_total}条 · commit {commit_sha[:7]}")
    print(f"   URL: https://{GH_OWNER}.github.io/{GH_REPO}/")


if __name__ == '__main__':
    main()
