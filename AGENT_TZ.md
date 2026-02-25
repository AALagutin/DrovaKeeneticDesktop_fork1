# ТЗ: drova-agent — Windows-агент для управления игровым ПК

## 1. Контекст и цель

### 1.1 Что такое система Drova

Система сдаёт в аренду игровые Windows ПК. Python-воркер (gate) запускается на Linux-сервере и управляет одним игровым ПК через SSH.

**Текущий flow:**
```
gate (Linux)  ──SSH──>  игровой ПК (Windows)
                         ├─ Shadow Defender (откат изменений после сессии)
                         ├─ Steam / Epic / Ubisoft / Wargaming лаунчеры
                         ├─ Реестр Windows (ограничения для арендатора)
                         └─ ESME агент Drova (auth_token в реестре)
```

**Polling цикл gate:**
1. `GamePCDiagnostic` — диагностика при старте воркера
2. `CheckDesktop` / `WaitNewDesktopSession` — ждать новой сессии
3. `BeforeConnect` — подготовка ПК перед тем как арендатор подключится
4. `WaitFinishOrAbort` — ждать конца сессии
5. `AfterDisconnect` — очистка после сессии

### 1.2 Проблемы SSH-подхода

- SSH соединение рвётся → команда прерывается на середине (SD enter без exit = ПК завис в shadow mode)
- Каждая команда = отдельный SSH RTT 50–200 мс; `BeforeConnect` занимает 3–5 секунд
- `psexec` для запуска explorer.exe нестабилен
- Нельзя мониторить запущенные процессы в реальном времени
- SSH порт открыт на игровом ПК (лишняя attack surface)

### 1.3 Цель

Разработать `drova-agent.exe` — Windows-сервис на Go, который:
1. Сам инициирует WebSocket-соединение к gate
2. Выполняет команды gate локально (без SSH RTT)
3. Стримит события о процессах (WMI)
4. Устанавливается и обновляется автоматически через SSH (один раз)
5. При отсутствии агента gate продолжает работать через SSH (fallback)

---

## 2. Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  Gate (Linux, Python asyncio)                                │
│                                                              │
│  DrovaPoll / DrovaSocket                                     │
│       │                                                      │
│       ▼                                                      │
│  HostController  ─────── AgentConnection (WebSocket сервер) │
│       │                       ▲                              │
│       │  fallback SSH          │ ws://gate:8765/agent/{id}  │
│       ▼                       │                              │
│  SSHExecutor              (постоянное соединение)            │
└──────────────────────────────────────────────────────────────┘
                                │
                         WebSocket (JSON)
                                │
┌──────────────────────────────────────────────────────────────┐
│  drova-agent.exe (Windows Service, Go)                       │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐   │
│  │  ws/     │  │ monitor/ │  │ winapi/  │  │  sd/      │   │
│  │ client   │  │ wmi      │  │ registry │  │ shadow    │   │
│  └──────────┘  └──────────┘  │ process  │  │ defender  │   │
│       │             │        │ session  │  └───────────┘   │
│       ▼             ▼        └──────────┘                   │
│  dispatcher ◄── event bus                                    │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 Транспорт

- Агент → Gate: `ws://<gate_host>:<gate_port>/agent/<host_id>`
- Протокол: JSON поверх WebSocket (text frames)
- Агент всегда **инициирует** соединение (исходящий трафик)
- Реконнект: экспоненциальный backoff 1s → 2s → 4s → 8s → max 30s
- Heartbeat: агент отправляет `ping` каждые 15 сек; gate отвечает `pong`
- Таймаут команды на gate: 30 сек (потом fallback на SSH)

### 2.2 Идентификация агента

`host_id` = значение из реестра `HKLM\SOFTWARE\Drova\Agent\host_id`
При первом запуске агент генерирует UUID и сохраняет в реестр.

Gate знает `host_id` через переменную окружения `WINDOWS_HOST_ID` (или берёт из `WINDOWS_HOST` + SSH-команда при установке).

---

## 3. Протокол сообщений

### 3.1 Формат

Все сообщения — JSON объекты.

**Gate → Agent (команды):**
```json
{
  "id": "uuid-v4",
  "cmd": "имя_команды",
  "params": { ... }
}
```

**Agent → Gate (ответы):**
```json
{
  "id": "uuid-v4",
  "ok": true,
  "result": { ... }
}
```
```json
{
  "id": "uuid-v4",
  "ok": false,
  "error": "текст ошибки"
}
```

**Agent → Gate (события, без id):**
```json
{
  "event": "имя_события",
  "data": { ... }
}
```

---

## 4. Команды (Gate → Agent)

### 4.1 Shadow Defender

#### `sd_enter`
Входит в Shadow Mode для указанных дисков.
```json
{ "cmd": "sd_enter", "params": { "password": "...", "drives": "CDE" } }
```
Результат:
```json
{ "ok": true, "result": { "exit_code": 0, "stdout": "..." } }
```
Реализация: `exec CmdTool.exe /pwd:"..." /enter:CDE /now`
Ожидание: 2 секунды после команды (SD требует время).

#### `sd_exit_reboot`
Выходит из Shadow Mode и перезагружает.
```json
{ "cmd": "sd_exit_reboot", "params": { "password": "...", "drives": "CDE" } }
```
Реализация: `exec CmdTool.exe /pwd:"..." /exit:CDE /reboot /now`

#### `sd_list`
Возвращает статус Shadow Defender.
```json
{ "cmd": "sd_list", "params": { "password": "..." } }
```
Результат:
```json
{ "ok": true, "result": { "exit_code": 0, "stdout": "Drive C: Protected\r\n..." } }
```

CmdTool.exe расположен: `C:\Program Files\Shadow Defender\CmdTool.exe`

---

### 4.2 Процессы

#### `kill_exe`
Завершает все процессы с указанным именем.
```json
{ "cmd": "kill_exe", "params": { "image": "steam.exe" } }
```
Реализация: перебрать все процессы через `CreateToolhelp32Snapshot`, завершить `TerminateProcess`.
Не возвращать ошибку если процесс не найден (exit 0).

#### `kill_pid`
Завершает процесс по PID.
```json
{ "cmd": "kill_pid", "params": { "pid": 1234 } }
```

#### `launch_in_session`
Запускает процесс в указанной Windows-сессии.
```json
{ "cmd": "launch_in_session", "params": { "exe": "explorer.exe", "session_id": 2 } }
```
Реализация: `WTSQueryUserToken(session_id)` → `CreateProcessAsUser`.
Аналог текущего `psexec -i 2 -d explorer.exe`.

---

### 4.3 Файловые операции

Все пути — Windows пути (могут содержать `AppData\...` без диска — агент разворачивает относительно профиля текущего пользователя сессии, или `C:\...` — абсолютные).

#### `file_read`
```json
{ "cmd": "file_read", "params": { "path": "AppData\\Local\\EpicGamesLauncher\\...\\GameUserSettings.ini" } }
```
Результат:
```json
{ "ok": true, "result": { "content_b64": "base64...", "size": 1234 } }
```
Ошибка если файл не существует.

#### `file_write`
```json
{
  "cmd": "file_write",
  "params": {
    "path": "C:\\Program Files (x86)\\Steam\\config\\loginusers.vdf",
    "content_b64": "base64..."
  }
}
```

#### `file_delete`
```json
{ "cmd": "file_delete", "params": { "path": "AppData\\Local\\Ubisoft Game Launcher\\user.dat" } }
```
Не возвращать ошибку если файл не существует.

#### `file_exists`
```json
{ "cmd": "file_exists", "params": { "path": "AppData\\Local\\Ubisoft Game Launcher\\ConnectSecureStorage.dat" } }
```
Результат:
```json
{ "ok": true, "result": { "exists": true } }
```

---

### 4.4 Реестр

#### `reg_set`
```json
{
  "cmd": "reg_set",
  "params": {
    "path": "HKCU\\Software\\Policies\\Microsoft\\Windows\\System",
    "value_name": "DisableCMD",
    "value_type": "REG_DWORD",
    "value": 2
  }
}
```
`value_type`: `REG_DWORD`, `REG_SZ`, `REG_BINARY`, `REG_EXPAND_SZ`, `REG_MULTI_SZ`
`value`: для `REG_DWORD` — число; для `REG_SZ` — строка; для `REG_BINARY` — base64.

#### `reg_delete_key`
Удаляет ключ реестра целиком (рекурсивно).
```json
{ "cmd": "reg_delete_key", "params": { "path": "HKLM\\SOFTWARE\\ITKey\\Esme\\servers\\{server_id}" } }
```

#### `reg_query`
```json
{
  "cmd": "reg_query",
  "params": {
    "path": "HKCU\\Software\\Policies\\Microsoft\\Windows\\System",
    "value_name": "DisableCMD"
  }
}
```
Результат:
```json
{ "ok": true, "result": { "value_type": "REG_DWORD", "value": 2 } }
```
Ошибка если ключ или значение не найдены.

#### `reg_query_esme`
Специальная команда — читает все `auth_token` из `HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers`.
```json
{ "cmd": "reg_query_esme" }
```
Результат:
```json
{
  "ok": true,
  "result": {
    "pairs": [
      { "server_id": "abc123...", "auth_token": "tok456..." },
      { "server_id": "def789...", "auth_token": "tok000..." }
    ]
  }
}
```

---

### 4.5 Сессия Windows

#### `get_session_id`
Возвращает ID активной Windows-сессии (аналог `qwinsta`).
```json
{ "cmd": "get_session_id" }
```
Результат:
```json
{ "ok": true, "result": { "session_id": 2, "username": "User" } }
```
Реализация: `WTSEnumerateSessions` → найти сессию со статусом `WTSActive`.

---

### 4.6 Служебные

#### `ping`
```json
{ "cmd": "ping" }
```
Результат: `{ "ok": true, "result": { "ts": "2024-01-01T12:00:00Z" } }`

#### `agent_info`
```json
{ "cmd": "agent_info" }
```
Результат:
```json
{
  "ok": true,
  "result": {
    "version": "1.0.0",
    "host_id": "uuid...",
    "os_version": "Windows 10 Pro 22H2",
    "uptime_sec": 3600
  }
}
```

---

## 5. События (Agent → Gate)

### 5.1 Подключение

Сразу после установки WebSocket соединения агент отправляет:
```json
{
  "event": "hello",
  "data": {
    "version": "1.0.0",
    "host_id": "uuid...",
    "os_version": "Windows 10 Pro 22H2",
    "build_time": "2024-01-01T00:00:00Z"
  }
}
```

### 5.2 Heartbeat (каждые 15 секунд)

```json
{
  "event": "heartbeat",
  "data": { "ts": "2024-01-01T12:00:00Z", "uptime_sec": 3600 }
}
```

### 5.3 Мониторинг процессов

#### `process_start`
Отправляется при запуске нового процесса (WMI `Win32_ProcessStartTrace`):
```json
{
  "event": "process_start",
  "data": {
    "pid": 1234,
    "ppid": 567,
    "exe": "anydesk.exe",
    "cmdline": "\"C:\\Program Files\\AnyDesk\\AnyDesk.exe\"",
    "session_id": 2,
    "ts": "2024-01-01T12:00:00.123Z"
  }
}
```

#### `process_stop`
```json
{
  "event": "process_stop",
  "data": {
    "pid": 1234,
    "exe": "anydesk.exe",
    "exit_code": 0,
    "ts": "2024-01-01T12:00:05.456Z"
  }
}
```

#### `window_title`
Отправляется через ~500 мс после старта процесса (окно успело нарисоваться):
```json
{
  "event": "window_title",
  "data": {
    "pid": 1234,
    "exe": "anydesk.exe",
    "title": "AnyDesk - Remote Desktop"
  }
}
```
Реализация: `EnumWindows` → `GetWindowThreadProcessId` → `GetWindowText`.

---

## 6. Модули агента (Go)

```
drova-agent/
├── main.go                   # точка входа, Windows service
├── service/
│   └── service.go            # golang.org/x/sys/windows/svc
├── ws/
│   ├── client.go             # WebSocket клиент + реконнект
│   └── dispatcher.go         # роутинг cmd → handler
├── handlers/
│   ├── sd.go                 # sd_enter, sd_exit_reboot, sd_list
│   ├── process.go            # kill_exe, kill_pid, launch_in_session
│   ├── file.go               # file_read, file_write, file_delete, file_exists
│   ├── registry.go           # reg_set, reg_delete_key, reg_query, reg_query_esme
│   ├── session.go            # get_session_id
│   └── info.go               # ping, agent_info
├── monitor/
│   └── wmi.go                # WMI Win32_ProcessStartTrace/StopTrace
├── winapi/
│   ├── windows.go            # syscall обёртки: EnumWindows, GetWindowText
│   └── process.go            # CreateToolhelp32Snapshot, TerminateProcess
└── config/
    └── config.go             # чтение env + реестр (host_id, gate URL)
```

### 6.1 Конфигурация агента

Агент читает конфигурацию при старте из переменных окружения Windows-сервиса (задаются при установке через `sc config`):

| Переменная | Описание | Пример |
|---|---|---|
| `DROVA_GATE_URL` | WebSocket URL gate | `ws://192.168.1.100:8765` |
| `DROVA_HOST_ID` | ID этого ПК (опционально, генерируется если нет) | `uuid-v4` |

### 6.2 Разворачивание путей AppData

Команды с относительными путями вида `AppData\Local\...`:
Агент раскрывает через `WTSQuerySessionInformation(session_id, WTSUserName)` → `GetUserProfileDirectory` → подставляет в путь.

Если пользовательская сессия не определена — использует `%USERPROFILE%` текущего процесса.

---

## 7. Gate-side изменения (Python)

### 7.1 Новые файлы

```
drova_desktop_keenetic/common/
├── agent_server.py       # asyncio WebSocket сервер (принимает агентов)
├── agent_client.py       # интерфейс для отправки команд агенту
└── host_controller.py    # HostController: агент → SSH fallback
```

### 7.2 `agent_server.py`

```python
class AgentServer:
    """asyncio WebSocket сервер. Хранит подключённых агентов по host_id."""

    async def start(self, host: str = "0.0.0.0", port: int = 8765): ...
    def get_agent(self, host_id: str) -> AgentConnection | None: ...
```

```python
class AgentConnection:
    """Соединение с одним агентом. Thread-safe очередь ответов."""

    host_id: str
    version: str
    connected_at: datetime
    last_heartbeat: datetime

    async def send_command(self, cmd: str, params: dict = {}, timeout: float = 30.0) -> dict:
        """Отправляет команду, ждёт ответа. Бросает TimeoutError или AgentCommandError."""
        ...

    def is_alive(self) -> bool:
        """True если last_heartbeat < 60 сек назад."""
        ...
```

### 7.3 `host_controller.py`

```python
class HostController:
    """
    Единый интерфейс управления игровым ПК.
    Если агент подключён — использует агента.
    Иначе — SSH (существующий код без изменений).
    """

    def __init__(self, host: str, ssh_conn: SSHClientConnection, agent: AgentConnection | None):
        ...

    # Все методы возвращают то же что и SSH-версии
    async def sd_enter(self) -> None: ...
    async def sd_exit_reboot(self) -> None: ...
    async def kill_exe(self, image: str) -> None: ...
    async def apply_patch(self, patch_class: type[IPatch]) -> None: ...
    async def get_session_id(self) -> int: ...
    async def launch_in_session(self, exe: str, session_id: int) -> None: ...
    async def reg_query_esme(self) -> list[tuple[str, str]]: ...
    async def reg_delete_key(self, path: str) -> None: ...

    @property
    def using_agent(self) -> bool: ...
```

### 7.4 Изменения существующих файлов

**`before_connect.py`** — заменить прямые вызовы `self.client.run()` и SFTP на `HostController`:
```python
# Было:
await self.client.run(str(ShadowDefenderCLI(...)))
# Стало:
await self.host_controller.sd_enter()
```

**`after_disconnect.py`** — аналогично.

**`gamepc_diagnostic.py`** — аналогично.

**`drova_poll.py`** — при создании SSH соединения дополнительно получать `AgentConnection` из `AgentServer` и передавать в `HostController`.

### 7.5 Конфигурация gate

Новые переменные окружения:

| Переменная | Описание | По умолчанию |
|---|---|---|
| `AGENT_SERVER_PORT` | Порт WebSocket сервера | `8765` |
| `AGENT_TIMEOUT` | Таймаут команды агента (сек) | `30` |
| `AGENT_FALLBACK_SSH` | Использовать SSH если агент недоступен | `true` |

---

## 8. Установка агента

### 8.1 Первичная установка (через SSH)

Gate при старте воркера проверяет наличие агента и устанавливает если нет:

```python
async def ensure_agent(ssh: SSHClientConnection, host_id: str, agent_server: AgentServer) -> bool:
    """
    1. Если агент уже подключён к WS → проверить версию → обновить если устарел
    2. Если SD активен → пропустить (нельзя устанавливать в shadow mode)
    3. sc query drova-agent → RUNNING? → ждать WS подключения 30 сек
    4. Если нет → SFTP копировать drova-agent.exe → sc create → sc start
    5. Ждать WS подключения 30 сек
    6. Если не подключился → продолжить через SSH (агент работает в фоне)
    """
```

**Команды установки через SSH:**
```
# Копировать бинарник
sftp.put("drova-agent.exe", "C:\\drova\\drova-agent.exe")

# Создать сервис
sc create drova-agent binPath= "C:\drova\drova-agent.exe" start= auto

# Задать переменные окружения для сервиса
reg add HKLM\SYSTEM\CurrentControlSet\Services\drova-agent\Environment /v DROVA_GATE_URL /t REG_SZ /d "ws://192.168.1.100:8765" /f
reg add HKLM\SYSTEM\CurrentControlSet\Services\drova-agent\Environment /v DROVA_HOST_ID /t REG_SZ /d "<host_id>" /f

# Запустить
sc start drova-agent
```

### 8.2 Обновление агента

Если агент подключён и `agent_info.version` < требуемой:
```
sc stop drova-agent
sftp.put("drova-agent-new.exe", "C:\\drova\\drova-agent.exe")
sc start drova-agent
ждать реконнект 30 сек
```

### 8.3 Сборка агента

```
# На CI (cross-compile для Windows amd64)
GOOS=windows GOARCH=amd64 go build -ldflags="-s -w -X main.Version=1.0.0" -o drova-agent.exe .
```

Размер бинарника: ~8–12 МБ (без CGO зависимостей).
WMI требует CGO: `CGO_ENABLED=1` + MinGW cross-компилятор.

Альтернатива без CGO для WMI: использовать `github.com/yusufpapurcu/wmi` (pure Go через COM).

---

## 9. Детали реализации

### 9.1 Shadow Defender + агент

Shadow Defender откатывает **все** изменения файловой системы при выходе из shadow mode, включая файлы агента.

**Проблема:** агент установлен → SD enter → reboot → агент исчез.

**Решение:** агент устанавливается **до** `sd_enter`. Gate проверяет:
1. SD активен сейчас? → Если да, агент работает в текущей сессии, но после reboot его нет.
2. `ensure_agent` вызывается только когда SD **не активен**.
3. После `sd_exit_reboot` gate ждёт реконнект агента (агент сохранён, SD откатил только то что было в shadow mode, сервис остаётся).

### 9.2 Параллельные операции реестра

`PatchWindowsSettings` применяет ~17 reg-ключей. Агент применяет их параллельно:
- Горутины с семафором на 5 параллельных операций
- Собирать все ошибки, возвращать список упавших

### 9.3 Разворачивание `AppData` путей

```go
func expandPath(path string, sessionID uint32) (string, error) {
    if filepath.IsAbs(path) {
        return path, nil
    }
    // path начинается с AppData\...
    profileDir, err := getUserProfileDir(sessionID)
    if err != nil {
        return "", err
    }
    return filepath.Join(profileDir, path), nil
}
```

### 9.4 Мониторинг процессов (WMI)

```go
// Подписка на старт/стоп процессов через WMI
type Win32_ProcessStartTrace struct {
    ProcessName string
    ProcessID   uint32
    ParentProcessID uint32
    SessionID   uint32
}
```

Использовать `github.com/yusufpapurcu/wmi` для подписки через `ExecNotificationQuery`.

### 9.5 Заголовки окон

```go
// 500 мс после process_start — проверить окна этого PID
time.AfterFunc(500*time.Millisecond, func() {
    title := getWindowTitleForPID(pid)
    if title != "" {
        sendEvent("window_title", ...)
    }
})
```

### 9.6 Обработка ошибок команд

- Если команда выполнена но вернула non-zero exit code (SD, reg) — возвращать `ok: true` с `exit_code` в результате. Gate сам решает что делать.
- Если Go-уровень ошибка (файл не найден, access denied) — возвращать `ok: false, error: "..."`.
- Таймаут команды на агенте: 25 сек (меньше чем gate-side 30 сек).

---

## 10. Что НЕ делает агент

- Не обращается к Drova API (это делает gate)
- Не знает про логику сессий (когда BeforeConnect, когда AfterDisconnect — решает gate)
- Не хранит состояние между командами (stateless executor)
- Не запускает Shadow Defender — только вызывает CmdTool.exe
- Не управляет сетью

---

## 11. Зависимости Go

```go
// go.mod
require (
    golang.org/x/sys v0.20.0                    // Windows API, registry, service
    github.com/gorilla/websocket v1.5.1          // WebSocket клиент
    github.com/yusufpapurcu/wmi v1.2.4           // WMI (pure Go через COM)
    github.com/google/uuid v1.6.0                // генерация host_id
)
```

**Важно:** сборка с `CGO_ENABLED=0` если не нужен WMI, `CGO_ENABLED=1` если нужен.

---

## 12. Последовательность разработки

### Этап 1 — Минимальный агент (без мониторинга)
- [ ] Windows service skeleton (start/stop)
- [ ] WebSocket клиент с реконнектом
- [ ] Dispatcher (cmd → handler)
- [ ] Handlers: `ping`, `agent_info`
- [ ] Handlers: `sd_enter`, `sd_exit_reboot`, `sd_list`
- [ ] Handlers: `kill_exe`
- [ ] Handlers: `file_read/write/delete/exists`
- [ ] Handlers: `reg_set`, `reg_query`, `reg_delete_key`, `reg_query_esme`
- [ ] Handlers: `get_session_id`, `launch_in_session`
- [ ] Gate: `AgentServer` + `AgentConnection`
- [ ] Gate: `HostController` (агент + SSH fallback)
- [ ] Gate: `ensure_agent` (SSH установка)
- [ ] Интеграция в `before_connect.py`, `after_disconnect.py`

### Этап 2 — Мониторинг процессов
- [ ] WMI подписка `Win32_ProcessStartTrace`
- [ ] WMI подписка `Win32_ProcessStopTrace`
- [ ] `window_title` через EnumWindows
- [ ] Gate: хранение событий процессов

### Этап 3 — Продакшн
- [ ] Автообновление агента
- [ ] Метрики (количество команд, latency)
- [ ] Подпись бинарника (Code Signing)
- [ ] Обход Windows Defender (whitelist или подпись)

---

## 13. Тесты

### Агент (Go)
- Unit: каждый handler с mock Windows API
- Integration: реальный Windows (GitHub Actions windows-latest)
- Тест реконнекта: gate падает и поднимается, агент переподключается

### Gate (Python)
- Существующие тесты не должны сломаться (SSH path)
- Новые: `HostController` с mock `AgentConnection` и mock SSH

---

## 14. Справочник: текущий SSH-код → команды агента

| Python класс | Текущая SSH команда | Команда агента |
|---|---|---|
| `ShadowDefenderCLI(enter)` | `& "C:\...\CmdTool.exe" /enter:CDE /now` | `sd_enter` |
| `ShadowDefenderCLI(exit,reboot)` | `& "C:\...\CmdTool.exe" /exit:CDE /reboot /now` | `sd_exit_reboot` |
| `ShadowDefenderCLI(list)` | `& "C:\...\CmdTool.exe" /list /now` | `sd_list` |
| `TaskKill(image)` | `taskkill.exe /f /IM steam.exe` | `kill_exe` |
| `sftp.get(remote, local)` | SFTP download | `file_read` |
| `sftp.put(local, remote)` | SFTP upload | `file_write` |
| `sftp.remove(path)` | SFTP delete | `file_delete` |
| `sftp.exists(path)` | SFTP exists | `file_exists` |
| `RegAdd(path, name, type, val)` | `reg add HKCU\... /v ... /t ... /d ...` | `reg_set` |
| `RegQuery(path, name)` | `reg query HKCU\... /v ...` | `reg_query` |
| `RegDeleteKey(path)` | `reg delete ... /f` | `reg_delete_key` |
| `RegQueryEsme()` | `reg query HKLM\...\Esme\servers /s /f auth_token` | `reg_query_esme` |
| `QWinSta()` | `qwinsta` + парсинг | `get_session_id` |
| `PsExec(explorer.exe, session=N)` | `psexec -i N -d explorer.exe` | `launch_in_session` |
