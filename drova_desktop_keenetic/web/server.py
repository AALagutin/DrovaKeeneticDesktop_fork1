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
    .container { max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }
    .card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 1.5rem; margin-bottom: 1.5rem; }
    .card-title { font-size: .8rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #6b7280; margin-bottom: 1rem; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th { font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; color: #9ca3af; font-weight: 600;
         padding: .5rem .6rem; text-align: left; border-bottom: 1px solid #f3f4f6; white-space: nowrap; }
    td { padding: .55rem .6rem; border-bottom: 1px solid #f9fafb; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }

    /* Worker status badge */
    .badge { display: inline-flex; align-items: center; gap: .3rem; padding: .2rem .55rem; border-radius: 20px; font-size: .7rem; font-weight: 600; white-space: nowrap; }
    .badge::before { content: ""; display: block; width: 6px; height: 6px; border-radius: 50%; }
    .badge-running  { background: #dcfce7; color: #166534; }
    .badge-running::before  { background: #22c55e; }
    .badge-stopped, .badge-disabled { background: #f3f4f6; color: #6b7280; }
    .badge-stopped::before, .badge-disabled::before { background: #d1d5db; }
    .badge-error { background: #fee2e2; color: #991b1b; }
    .badge-error::before { background: #ef4444; animation: blink 1.5s infinite; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }

    /* Diagnostic icons */
    .di { display: inline-flex; align-items: center; justify-content: center;
          width: 1.55rem; height: 1.55rem; border-radius: 5px;
          font-size: .8rem; line-height: 1; cursor: default; }
    .di + .di { margin-left: 2px; }
    .di-ok       { background: #dcfce7; color: #166534; }
    .di-err      { background: #fee2e2; color: #991b1b; }
    .di-warn     { background: #fef3c7; color: #92400e; }
    .di-unk      { background: #f3f4f6; color: #d1d5db; }
    .di-sd-on    { background: #dbeafe; color: #1d4ed8; }
    .di-sd-off   { background: #f3f4f6; color: #9ca3af; }
    .di-sess-idle    { background: #f3f4f6; color: #9ca3af; }
    .di-sess-desk    { background: #dbeafe; color: #1d4ed8; }
    .di-sess-other   { background: #fef3c7; color: #b45309; }

    /* Buttons */
    .btn { padding: .28rem .6rem; border: none; border-radius: 6px; cursor: pointer;
           font-size: .78rem; font-weight: 500; transition: opacity .15s; white-space: nowrap; }
    .btn:hover { opacity: .75; }
    .btn-stop     { background: #fee2e2; color: #b91c1c; }
    .btn-start    { background: #dcfce7; color: #15803d; }
    .btn-reboot   { background: #fef3c7; color: #92400e; }
    .btn-shutdown { background: #fce7f3; color: #9d174d; }
    .btn-del      { background: #f3f4f6; color: #6b7280; margin-left: .2rem; }
    .actions      { display: flex; gap: .25rem; flex-wrap: wrap; align-items: center; }

    .pid { font-size: .72rem; color: #9ca3af; font-family: monospace; }
    form { display: flex; gap: .5rem; flex-wrap: wrap; align-items: flex-end; }
    .field { display: flex; flex-direction: column; gap: .3rem; }
    label { font-size: .75rem; font-weight: 600; color: #6b7280; }
    input { padding: .45rem .75rem; border: 1px solid #e5e7eb; border-radius: 6px; font-size: .875rem; outline: none; transition: border-color .15s; }
    input:focus { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,.15); }
    .btn-primary { background: #0f172a; color: #fff; padding: .45rem 1rem; }
    .empty { color: #9ca3af; text-align: center; padding: 1.5rem; font-size: .875rem; }
    .updated { font-size: .7rem; color: #d1d5db; margin-top: .75rem; text-align: right; }
    .err-msg { color: #b91c1c; font-size: .8rem; margin-top: .5rem; display: none; }

    .legend { font-size: .72rem; color: #9ca3af; margin-top: .75rem; display: flex; flex-wrap: wrap; gap: .5rem .9rem; }
    .legend-item { display: flex; align-items: center; gap: .3rem; }
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
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Хост</th>
            <th>Воркер</th>
            <th title="SSH: доступность и корректность пароля">SSH</th>
            <th title="Shadow Defender: теневой режим">SD</th>
            <th title="Ограничения реестра применены">Огр.</th>
            <th title="Текущий Drova-сеанс">Сессия</th>
            <th>PID</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody id="hosts-body">
          <tr><td colspan="8" class="empty">Загрузка...</td></tr>
        </tbody>
      </table>
    </div>
    <div class="legend">
      <span class="legend-item"><span class="di di-ok">✓</span> применено / OK</span>
      <span class="legend-item"><span class="di di-err">✗</span> ошибка</span>
      <span class="legend-item"><span class="di di-warn">✗</span> не применено (ожидаемо)</span>
      <span class="legend-item"><span class="di di-unk">?</span> нет данных</span>
      <span class="legend-item"><span class="di di-sd-on">🔒</span> SD: в теневом режиме</span>
      <span class="legend-item"><span class="di di-sd-off">🔓</span> SD: не защищён</span>
      <span class="legend-item"><span class="di di-sess-desk">🖥</span> сеанс: рабочий стол</span>
      <span class="legend-item"><span class="di di-sess-other">▷</span> сеанс: не рабочий стол</span>
      <span class="legend-item"><span class="di di-sess-idle">○</span> нет сеанса</span>
    </div>
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

// ---- Diagnostic icon helpers ----

function sshIcon(ok) {
  if (ok === true)  return '<span class="di di-ok"  title="SSH: подключение успешно">✓</span>';
  if (ok === false) return '<span class="di di-err" title="SSH: недоступен или неверный пароль">✗</span>';
  return '<span class="di di-unk" title="SSH: нет данных">?</span>';
}

function sdIcon(mode) {
  if (mode === true)  return '<span class="di di-sd-on"  title="Shadow Defender: теневой режим активен">🔒</span>';
  if (mode === false) return '<span class="di di-sd-off" title="Shadow Defender: режим не активен">🔓</span>';
  return '<span class="di di-unk" title="Shadow Defender: нет данных">?</span>';
}

function restIcon(ok, shadowMode) {
  if (ok === null || ok === undefined)
    return '<span class="di di-unk" title="Ограничения: нет данных">?</span>';
  if (ok === true)
    return '<span class="di di-ok" title="Ограничения реестра применены">✓</span>';
  // ok === false
  if (shadowMode === true)
    return '<span class="di di-err" title="SD активен, но ограничения НЕ применены — проблема!">✗</span>';
  return '<span class="di di-warn" title="Ограничения не применены (SD не активен — это нормально)">✗</span>';
}

function sessIcon(state) {
  if (state === 'desktop')
    return '<span class="di di-sess-desk"  title="Активный сеанс: рабочий стол">🖥</span>';
  if (state === 'non_desktop')
    return '<span class="di di-sess-other" title="Активный сеанс: не рабочий стол">▷</span>';
  if (state === 'idle')
    return '<span class="di di-sess-idle" title="Нет активного сеанса">○</span>';
  return '<span class="di di-unk" title="Сессия: нет данных">?</span>';
}

function fmtChecked(ts) {
  if (!ts) return 'не проверено';
  const ago = Math.round(Date.now() / 1000 - ts);
  if (ago < 60)  return ago + 'с назад';
  if (ago < 3600) return Math.round(ago / 60) + 'мин назад';
  return new Date(ts * 1000).toLocaleTimeString();
}

// ---- Refresh ----

async function refresh() {
  const r = await api('/api/hosts');
  const hosts = await r.json();
  const tbody = document.getElementById('hosts-body');
  if (!hosts.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">Нет хостов. Добавьте первый ниже.</td></tr>';
  } else {
    tbody.innerHTML = hosts.map(h => {
      const label = STATUS_LABELS[h.status] || h.status;
      const d = h.diag || {};
      const checked = fmtChecked(d.last_checked);

      const actionBtn = h.running
        ? `<button class="btn btn-stop"   onclick="stopHost('${h.host}')">Стоп</button>`
        : `<button class="btn btn-start"  onclick="startHost('${h.host}')">Старт</button>`;

      const pid = h.pid ? `<span class="pid">${h.pid}</span>` : '—';

      return `<tr>
        <td>${h.host}</td>
        <td><span class="badge badge-${h.status}">${label}</span></td>
        <td>${sshIcon(d.ssh_ok)}</td>
        <td>${sdIcon(d.shadow_mode)}</td>
        <td>${restIcon(d.restrictions_ok, d.shadow_mode)}</td>
        <td title="Проверено: ${checked}">${sessIcon(d.session_state)}</td>
        <td>${pid}</td>
        <td class="actions">
          ${actionBtn}
          <button class="btn btn-reboot"   onclick="rebootHost('${h.host}')"   title="Перезагрузить Windows">↺</button>
          <button class="btn btn-shutdown" onclick="shutdownHost('${h.host}')" title="Выключить Windows">⏻</button>
          <button class="btn btn-del"      onclick="delHost('${h.host}')">&#x2715;</button>
        </td>
      </tr>`;
    }).join('');
  }
  document.getElementById('updated').textContent = 'Обновлено: ' + new Date().toLocaleTimeString();
}

// ---- Actions ----

async function startHost(host) {
  await api(`/api/hosts/${encodeURIComponent(host)}/start`, 'POST');
  refresh();
}

async function stopHost(host) {
  await api(`/api/hosts/${encodeURIComponent(host)}/stop`, 'POST');
  refresh();
}

async function rebootHost(host) {
  if (!confirm('Перезагрузить ' + host + '?\nВоркер автоматически переподключится после перезагрузки.')) return;
  await api(`/api/hosts/${encodeURIComponent(host)}/reboot`, 'POST');
  refresh();
}

async function shutdownHost(host) {
  if (!confirm('Выключить ' + host + '?\nХост нужно будет включить вручную.')) return;
  await api(`/api/hosts/${encodeURIComponent(host)}/shutdown`, 'POST');
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


async def _handle_reboot(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    host = request.match_info["host"]
    try:
        await manager.reboot_host(host)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.json_response({"ok": True})


async def _handle_shutdown(request: web.Request) -> web.Response:
    manager: WorkerManager = request.app[_MANAGER_KEY]
    host = request.match_info["host"]
    try:
        await manager.shutdown_host(host)
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
    app.router.add_post("/api/hosts/{host}/reboot", _handle_reboot)
    app.router.add_post("/api/hosts/{host}/shutdown", _handle_shutdown)
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
