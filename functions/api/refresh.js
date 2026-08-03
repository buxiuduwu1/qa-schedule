// Cloudflare Pages Function: 触发 QA 排期刷新
// 访问 https://qa-schedule.pages.dev/api/refresh 触发 GitHub Actions
// 部署方式: wrangler pages deploy . --project-name qa-schedule

export async function onRequest(context) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  if (context.request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    // 调用 GitHub Actions workflow_dispatch
    const resp = await fetch(
      'https://api.github.com/repos/buxiuduwu1/qa-schedule/actions/workflows/refresh.yml/dispatches',
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${context.env.GH_PAT}`,
          'Accept': 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
          'User-Agent': 'qa-schedule-refresh-worker',
        },
        body: JSON.stringify({ ref: 'main' }),
      }
    );

    if (resp.status === 204 || resp.status === 200) {
      return new Response(JSON.stringify({ ok: true, message: '刷新已触发，约1-2分钟后完成' }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }
    const errText = await resp.text();
    return new Response(JSON.stringify({ ok: false, message: `GitHub 响应 ${resp.status}: ${errText.slice(0, 200)}` }), {
      status: 502,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, message: e.message }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }
}
