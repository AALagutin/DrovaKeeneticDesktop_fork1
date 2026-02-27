import base64
import hmac
import json
import logging

from aiohttp import web

from drova_desktop_keenetic.web.manager import WorkerManager

logger = logging.getLogger(__name__)

_MANAGER_KEY: web.AppKey["WorkerManager"] = web.AppKey("manager")

_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Drova — Управление хостами</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: #f0f2f5; color: #1a1a1a; }
    header { background: #0f172a; color: #fff; padding: 1rem 2rem; display: flex; align-items: center; gap: .75rem; }
    header h1 { margin: 0; font-size: 1.1rem; font-weight: 600; letter-spacing: -.01em; }
    .container { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    .card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 1.5rem; margin-bottom: 1.5rem; }
    .card-title { font-size: .8rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #6b7280; margin-bottom: 1rem; }
    table { width: 100%; border-collapse: collapse; }
    th { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: #9ca3af; font-weight: 600; padding: .5rem .75rem; text-align: left; border-bottom: 1px solid #f3f4f6; }
    td { padding: .6rem .75rem; border-bottom: 1px solid #f9fafb; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    .badge { display: inline-flex; align-items: center; gap: .3rem; padding: .25rem .6rem; border-radius: 20px; font-size: .72rem; font-weight: 600; }
    .badge::before { content: ""; display: block; width: 6px; height: 6px; border-radius: 50%; }
    .badge-running { background: #dcfce7; color: #166534; }
    .badge-running::before { background: #22c55e; }
    .badge-stopped, .badge-disabled { background: #f3f4f6; color: #6b7280; }
    .badge-stopped::before, .badge-disabled::before { background: #d1d5db; }
    .badge-error { background: #fee2e2; color: #991b1b; }
    .badge-error::before { background: #ef4444; animation: blink 1.5s infinite; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }
    .btn { padding: .3rem .7rem; border: none; border-radius: 6px; cursor: pointer; font-size: .8rem; font-weight: 500; transition: opacity .15s; white-space: nowrap; }
    .btn:hover { opacity: .8; }
    .btn-stop { background: #fee2e2; color: #b91c1c; }
    .btn-start { background: #dcfce7; color: #15803d; }
    .btn-del { background: #f3f4f6; color: #6b7280; margin-left: .25rem; }
    .pid { font-size: .75rem; color: #9ca3af; font-family: monospace; }
    form { display: flex; gap: .5rem; flex-wrap: wrap; align-items: flex-end; }
    .field { display: flex; flex-direction: column; gap: .3rem; }
    label { font-size: .75rem; font-weight: 600; color: #6b7280; }
    input { padding: .45rem .75rem; border: 1px solid #e5e7eb; border-radius: 6px; font-size: .875rem; outline: none; transition: border-color .15s; }
    input:focus { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,.15); }
    .btn-primary { background: #0f172a; color: #fff; padding: .45rem 1rem; }
    .empty { color: #9ca3af; text-align: center; padding: 1.5rem; font-size: .875rem; }
    .updated { font-size: .7rem; color: #d1d5db; margin-top: .75rem; text-align: right; }
    .err-msg { color: #b91c1c; font-size: .8rem; margin-top: .5rem; display: none; }
  </style>
</head>
<body>
<header>
  <svg width="20" height="20" fill="none" viewBox="0 0 24 24">
    <path fill="currentColor" d="M3 6a1 1 0 011-1h16a1 1 0 110 2H4a1 1 0 01-1-1zm0 6a1 1 0 011-1h16a1 1 0 110 2H4a1 1 0 01-1-1zm0 6a1 1 0 011-1h10a1 1 0 110 2H4a1 1 0 01-1-1z"/>
  </svg>
  <h1>Drova — Управление хостами</h1>
</header>
<div class="container">
  <div class="card">
    <div class="card-title">Активные хосты</div>
    <table>
      <thead>
        <tr><th>Хост</th><th>Статус</th><th>PID</th><th>Действия</th></tr>
      </thead>
      <tbody id="hosts-body">
        <tr><td colspan="4" class="empty">Загрузка...</td></tr>
      </tbody>
    </table>
    <div class="updated" id="updated"></div>
  </div>
  <div class="card">
    <div class="card-title">Добавить хост</div>
    <form id="add-form">
      <div class="field">
        <label>Хост (IP / имя)</label>
        <input name="host" placeholder="192.168.1.100" required>
      </div>
      <div class="field">
        <label>Логин</label>
        <input name="login" placeholder="из defaults">
      </div>
      <div class="field">
        <label>Пароль</label>
        <input name="password" type="password" placeholder="из defaults">
      </div>
      <button class="btn btn-primary" type="submit">Добавить</button>
    </form>
    <div class="err-msg" id="add-err"></div>
  </div>
</div>
<script>
const STATUS_LABELS = {
  running:  'Работает',
  stopped:  'Остановлен',
  disabled: 'Отключён',
  error:    'Ошибка',
};

async function api(url, method = 'GET', body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.body = JSON.stringify(body);
    opts.headers['Content-Type'] = 'application/json';
  }
  return fetch(url, opts);
}

async function refresh() {
  const r = await api('/api/hosts');
  const hosts = await r.json();
  const tbody = document.getElementById('hosts-body');
  if (!hosts.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">Нет хостов. Добавьте первый ниже.</td></tr>';
  } else {
    tbody.innerHTML = hosts.map(h => {
      const label = STATUS_LABELS[h.status] || h.status;
      const actionBtn = h.running
        ? `<button class="btn btn-stop" onclick="stopHost('${h.host}')">Стоп</button>`
        : `<button class="btn btn-start" onclick="startHost('${h.host}')">Старт</button>`;
      const pid = h.pid ? `<span class="pid">${h.pid}</span>` : '—';
      return `<tr>
        <td>${h.host}</td>
        <td><span class="badge badge-${h.status}">${label}</span></td>
        <td>${pid}</td>
        <td>${actionBtn}<button class="btn btn-del" onclick="delHost('${h.host}')">&#x2715;</button></td>
      </tr>`;
    }).join('');
  }
  document.getElementById('updated').textContent = 'Обновлено: ' + new Date().toLocaleTimeString();
}

async function startHost(host) {
  await api(`/api/hosts/${encodeURIComponent(host)}/start`, 'POST');
  refresh();
}

async function stopHost(host) {
  await api(`/api/hosts/${encodeURIComponent(host)}/stop`, 'POST');
  refresh();
}

async function delHost(host) {
  if (!confirm('Удалить хост ' + host + ' из конфигурации?')) return;
  await api(`/api/hosts/${encodeURIComponent(host)}`, 'DELETE');
  refresh();
}

document.getElementById('add-form').addEventListener('submit', async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  const errEl = document.getElementById('add-err');
  const r = await api('/api/hosts', 'PUT', data);
  if (!r.ok) {
    const j = await r.json();
    errEl.textContent = j.error;
    errEl.style.display = 'block';
    return;
  }
  errEl.style.display = 'none';
  e.target.reset();
  refresh();
});

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def _check_auth(request: web.Request, user: str, password: str) -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode()
    except Exception:
        return False
    req_user, _, req_password = decoded.partition(":")
    return hmac.compare_digest(req_user, user) and hmac.compare_digest(req_password, password)


def _make_auth_middleware(user: str, password: str):
    @web.middleware
    async def middleware(request: web.Request, handler):
        if not _check_auth(request, user, password):
            return web.Response(
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Drova"'},
                text="Unauthorized",
            )
        return await handler(request)

    return middleware


async def _handle_index(request: web.Request) -> web.Response:
    return web.Response(content_type="text/html", text=_HTML)


async def _handle_get_hosts(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    return web.json_response(manager.get_status())


async def _handle_start(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    host = request.match_info["host"]
    try:
        await manager.start_worker(host)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.json_response({"ok": True})


async def _handle_stop(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    host = request.match_info["host"]
    try:
        await manager.stop_worker(host)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.json_response({"ok": True})


async def _handle_add_host(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    host = str(data.get("host", "")).strip()
    if not host:
        return web.json_response({"error": "host is required"}, status=400)
    try:
        await manager.add_host(
            host=host,
            login=str(data.get("login", "")).strip() or None,
            password=str(data.get("password", "")).strip() or None,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    return web.json_response({"ok": True})


async def _handle_remove_host(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    host = request.match_info["host"]
    try:
        await manager.remove_host(host)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.json_response({"ok": True})


def create_app(manager: WorkerManager, user: str, password: str) -> web.Application:
    app = web.Application(middlewares=[_make_auth_middleware(user, password)])
    app[_MANAGER_KEY] = manager
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/hosts", _handle_get_hosts)
    app.router.add_post("/api/hosts/{host}/start", _handle_start)
    app.router.add_post("/api/hosts/{host}/stop", _handle_stop)
    app.router.add_put("/api/hosts", _handle_add_host)
    app.router.add_delete("/api/hosts/{host}", _handle_remove_host)
    return app


async def run_server(manager: WorkerManager, port: int, user: str, password: str) -> None:
    app = create_app(manager, user, password)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("web: listening on http://0.0.0.0:%d", port)
