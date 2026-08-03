// Cloudflare Pages Function: 值班排班数据 API
// GET  /api/duty  -> 读取排班数据
// POST /api/duty  -> 操作排班（swap/add/remove/reset）
// 数据存 KV (DUTY_KV)，键名 "schedule"

const KEY = 'schedule';
const DEFAULT_DATA = {
  people: ['张三', '李四', '王五', '赵六', '孙七'],
  start_date: getThisMonday(),
  updated_at: new Date().toISOString(),
};

function getThisMonday() {
  const now = new Date();
  const day = now.getDay() || 7;
  now.setDate(now.getDate() - day + 1);
  now.setHours(0, 0, 0, 0);
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

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

export async function onRequest(context) {
  if (context.request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  const kv = context.env.DUTY_KV;
  if (!kv) {
    return json({ ok: false, message: 'KV 未绑定' }, 500);
  }

  // GET：读取
  if (context.request.method === 'GET') {
    try {
      let data = await kv.get(KEY, 'json');
      if (!data || !data.people || data.people.length === 0) {
        data = DEFAULT_DATA;
        await kv.put(KEY, JSON.stringify(data));
      }
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

      let data = await kv.get(KEY, 'json');
      if (!data || !data.people) {
        data = DEFAULT_DATA;
      }
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
        data.start_date = body.start_date || getThisMonday();
      } else {
        return json({ ok: false, message: '未知操作: ' + action }, 400);
      }

      data.updated_at = new Date().toISOString();
      await kv.put(KEY, JSON.stringify(data));
      return json({ ok: true, data });
    } catch (e) {
      return json({ ok: false, message: '操作失败: ' + e.message }, 500);
    }
  }

  return json({ ok: false, message: '仅支持 GET/POST' }, 405);
}
