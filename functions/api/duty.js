// Cloudflare Pages Function: 值班排班数据 API（GitHub 存储版）
// GET  /api/duty  -> 读取排班数据（GitHub duty/data.json）
// POST /api/duty  -> 操作排班（swap/add/remove/reset），写回 GitHub
//
// 数据存 GitHub 仓库 buxiuduwu1/qa-schedule 的 duty/data.json
// 每次修改都会产生一个 commit，有完整版本历史

const OWNER = 'buxiuduwu1';
const REPO = 'qa-schedule';
const DATA_PATH = 'duty/data.json';
const API_BASE = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${DATA_PATH}`;
const RAW_BASE = `https://raw.githubusercontent.com/${OWNER}/${REPO}/main/${DATA_PATH}`;

const DEFAULT_DATA = {
  people: ['吴淦淦', '李研锋', '张家像', '周旋之', '杨钦', '张海志'],
  start_date: '2026-08-03',
  updated_at: new Date().toISOString(),
};

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json; charset=utf-8' },
  });
}

function makeHeaders(env) {
  return {
    'Authorization': `Bearer ${env.GH_PAT}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
    'User-Agent': 'qa-schedule-duty-worker',
  };
}

async function readData(env) {
  // 直接走 GitHub API 读取（实时，拿到 sha），不用 raw（raw 有 CDN 缓存延迟）
  const resp = await fetch(API_BASE, { headers: makeHeaders(env) });
  if (!resp.ok) throw new Error('GitHub 读取失败: ' + resp.status);
  const meta = await resp.json();
  // 正确解码 UTF-8：atob 得到 Latin-1 字符串，需转 Uint8Array 再用 TextDecoder
  const binary = atob(meta.content.replace(/\n/g, ''));
  const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
  const text = new TextDecoder('utf-8').decode(bytes);
  const data = JSON.parse(text);
  data._sha = meta.sha;
  return data;
}

async function writeData(env, data) {
  // 获取当前 sha
  const getResp = await fetch(API_BASE, { headers: makeHeaders(env) });
  if (!getResp.ok) throw new Error('GitHub 读取失败: ' + getResp.status);
  const meta = await getResp.json();
  const sha = meta.sha;

  const body = {
    message: '值班排班更新',
    content: btoa(unescape(encodeURIComponent(JSON.stringify(data, null, 2)))),
    branch: 'main',
    sha: sha,
  };

  const putResp = await fetch(API_BASE, {
    method: 'PUT',
    headers: makeHeaders(env),
    body: JSON.stringify(body),
  });
  if (!putResp.ok) {
    const err = await putResp.text();
    throw new Error('GitHub 写入失败: ' + putResp.status + ' ' + err.slice(0, 200));
  }
  return putResp.json();
}

export async function onRequest(context) {
  if (context.request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  // GET：读取
  if (context.request.method === 'GET') {
    try {
      const data = await readData(context.env);
      delete data._sha;
      return json({ ok: true, data });
    } catch (e) {
      return json({ ok: false, message: '读取失败: ' + e.message }, 500);
    }
  }

  // POST：操作
  if (context.request.method === 'POST') {
    try {
      const body = await context.request.json();
      const action = body.action;

      const data = await readData(context.env);
      if (!data.people) data.people = DEFAULT_DATA.people;
      data.people = data.people.filter(p => p && p.trim());

      if (action === 'swap') {
        const i = parseInt(body.i);
        const j = parseInt(body.j);
        if (isNaN(i) || isNaN(j) || i < 0 || j < 0 || i >= data.people.length || j >= data.people.length) {
          return json({ ok: false, message: '索引无效' }, 400);
        }
        [data.people[i], data.people[j]] = [data.people[j], data.people[i]];
      } else if (action === 'add') {
        const name = (body.name || '').trim();
        if (!name) return json({ ok: false, message: '姓名不能为空' }, 400);
        if (data.people.includes(name)) return json({ ok: false, message: `${name} 已在列表中` }, 400);
        data.people.push(name);
      } else if (action === 'remove') {
        const i = parseInt(body.index);
        if (isNaN(i) || i < 0 || i >= data.people.length) {
          return json({ ok: false, message: '索引无效' }, 400);
        }
        data.people.splice(i, 1);
      } else if (action === 'reset') {
        data.people = (body.people || DEFAULT_DATA.people).filter(p => p && p.trim());
        if (data.people.length === 0) return json({ ok: false, message: '人员不能为空' }, 400);
        data.start_date = body.start_date || data.start_date || '2026-08-03';
      } else {
        return json({ ok: false, message: '未知操作: ' + action }, 400);
      }

      data.updated_at = new Date().toISOString();
      await writeData(context.env, data);
      delete data._sha;
      return json({ ok: true, data });
    } catch (e) {
      return json({ ok: false, message: '操作失败: ' + e.message }, 500);
    }
  }

  return json({ ok: false, message: '仅支持 GET/POST' }, 405);
}
