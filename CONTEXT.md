# CONTEXT — drova-keenetic-desktop, ветка claude/review-drova-keenetic-fork-qjpRj

## Что это

Python-воркер (gate) на Linux управляет игровым Windows ПК через SSH.
Сдаёт ПК в аренду: до сессии применяет ограничения, после — откатывает через Shadow Defender.

**Entrypoints:**
- `drova_poll` — polling-режим: сам мониторит Drova API, ждёт сессий
- `drova_socket` — socket-режим: слушает порт, запускается по внешнему сигналу

## Структура файлов

```
drova_desktop_keenetic/
  common/
    commands.py          # билдеры CLI-команд: PsExec, TaskKill, ShadowDefenderCLI,
                         # RegAdd/Query/DeleteKey, RegQueryEsme, QWinSta
    patch.py             # патчи перед сессией: ALL_PATCHES = (
                         #   EpicGamesAuthDiscard, SteamAuthDiscard,
                         #   UbisoftAuthDiscard, WargamingAuthDiscard,
                         #   PatchWindowsSettings)
    before_connect.py    # SD enter → kill launchers → apply ALL_PATCHES
    after_disconnect.py  # SD exit+reboot
    gamepc_diagnostic.py # диагностика при старте: cleanup regs → SD enter →
                         # apply patches → verify registry → SD exit+reboot
    helpers.py           # BaseDrovaMerchantWindows, CheckDesktop,
                         # WaitFinishOrAbort, WaitNewDesktopSession, RebootRequired
    drova_poll.py        # DrovaPoll: основной polling loop
    drova_socket.py      # DrovaSocket: socket-режим
    drova_server_binary.py  # DrovaBinaryProtocol: проксирование TCP на порт 7985
    drova.py             # Drova API: get_latest_session, get_product_info,
                         # check_credentials, StatusEnum, SessionsEntity
    contants.py          # имена env-переменных
  bin/
    drova_poll.py        # entrypoint: single-host (env vars) или multi-host (DROVA_CONFIG)
    drova_socket.py      # entrypoint
  tests/
    conftest.py          # фикстура test_env: подставляет все env vars
    test_common.py       # unit: PsExec, RegQueryEsme, QWinSta, parseAllAuthCodes
    test_helpers.py
    test_poll.py
    test_socket.py
scripts/
  rollback_restrictions.ps1  # ручной откат реестровых ограничений на Windows
AGENT_TZ.md             # ТЗ на будущего Go-агента (не реализован)
```

## Env-переменные

| Переменная | Описание |
|---|---|
| `WINDOWS_HOST` | IP игрового ПК |
| `WINDOWS_LOGIN` | SSH логин |
| `WINDOWS_PASSWORD` | SSH пароль |
| `SHADOW_DEFENDER_PASSWORD` | пароль Shadow Defender |
| `SHADOW_DEFENDER_DRIVES` | диски для SD, например `CDE` |
| `DROVA_CONFIG` | путь к JSON multi-host конфигу (опционально) |
| `DROVA_SOCKET_LISTEN` | порт для socket-режима |

**Multi-host JSON формат** (`DROVA_CONFIG`):
```json
{
  "defaults": { "login": "user", "password": "pass",
                "shadow_defender_password": "sdpass", "shadow_defender_drives": "C" },
  "hosts": [
    { "host": "192.168.1.10" },
    { "host": "192.168.1.11", "login": "other", "password": "other" }
  ]
}
```

## Ключевые классы

### `PatchWindowsSettings` (patch.py)
Выставляет ~17 реестровых ключей параллельно (Semaphore=5):
- Отключает CMD, TaskManager, VBScript, PowerShell
- Запрещает выключение/выход через Start
- Отключает regedit, mmc, gpedit, anydesk, rustdesk, soundpad и др. через DisallowRun
- Убивает `explorer.exe` → применяет патчи → определяет session_id через `QWinSta` → запускает `explorer.exe` через `PsExec -i {session_id} -d -accepteula` **без** `-u/-p` (без credentials)

### `QWinSta` (commands.py)
`parse_active_session_id(stdout)` — парсит ID активной сессии, поддерживает EN и RU Windows (`Active`/`Активный`).

### `RegQueryEsme` (commands.py)
- `parseAuthCode(stdout)` — одна пара (server_id, auth_token), кидает `DuplicateAuthCode` если > 1
- `parseAllAuthCodes(stdout)` — все пары; используется в `_cleanup_stale_registrations`

### `GamePCDiagnostic` (gamepc_diagnostic.py)
Запускается при старте воркера если нет активных сессий:
1. `_cleanup_stale_registrations` — проверяет все reg-записи через Drova API, удаляет невалидные
2. `_sd_enter` → wait 2s → `_sd_log_status`
3. `_apply_restrictions` (все патчи, логирует OK/FAILED)
4. `_verify_all_restrictions` — RegQuery каждого ключа
5. `_sd_exit_reboot` — откат (в finally)

### `DrovaPoll` (drova_poll.py)
```
serve():
  _run_startup_diagnostic()   # GamePCDiagnostic
  _waitif_session_desktop_exists()  # если сессия уже есть — дождаться конца
  polling():                  # бесконечный цикл
    SSH connect
    CheckDesktop / WaitNewDesktopSession
    BeforeConnect → WaitFinishOrAbort → AfterDisconnect
    обработка: RebootRequired → AfterDisconnect
               DuplicateAuthCode → предупреждение + sleep(1)
               ChannelOpenError/OSError → ssh unreachable
```

## Что сделано в этой ветке (относительно оригинала)

1. **fix**: Epic Games путь (`WindowsEditor` → правильный)
2. **feat**: `GamePCDiagnostic` — диагностика при старте воркера
3. **feat**: cleanup невалидных server registrations из реестра
4. **feat**: multi-host конфиг через `DROVA_CONFIG`
5. **fix**: defer env var reads (не читать при импорте)
6. **refactor**: структурированные краткие логи
7. **feat**: `scripts/rollback_restrictions.ps1` — ручной откат
8. **fix**: `QWinSta.parse_active_session_id` — RU Windows + bytes/str
9. **fix**: динамическое определение session_id перед запуском explorer
10. **fix**: убрать `gpupdate` (блокировал на 5-8 сек)
11. **perf**: параллельные reg patches с Semaphore(5)
12. **fix**: PowerShell `&` оператор для CmdTool.exe
13. **fix**: `PsExec` без `-u/-p` для explorer.exe
14. **debug**: INFO-логи для qwinsta и psexec результатов

## Запуск тестов

```bash
poetry install
poetry run pytest drova_desktop_keenetic/tests/ -v
```

Тесты только unit (без SSH, без Windows). Все async-тесты через `pytest-asyncio`.

## Известные особенности / ловушки

- **SD + изменения**: Shadow Defender откатывает всё после reboot. BeforeConnect применяет патчи УЖЕ в SD-режиме — значит после сессии они исчезают. Это намеренно.
- **PsExec без credentials**: `PsExec(command="explorer.exe", user="", password="")` — специально без `-u/-p`, иначе explorer запускается под другим пользователем и не видит Desktop.
- **encoding=windows-1251**: все SSH соединения открываются с `encoding="windows-1251"` (русская Windows).
- **RebootRequired**: если `RegQueryEsme` не находит auth_token → нужен reboot (ESME не запустился).
- **DuplicateAuthCode**: два server_id в реестре → `_cleanup_stale_registrations` должен был очистить при старте.
- **`ShadowDefenderCLI` commit action**: есть `case "commit"` но `self.drives.split("")` — баг (split по пустой строке). Не используется в рабочем коде.

## Следующие возможные задачи

- Тесты для `GamePCDiagnostic` (сейчас не покрыт)
- Тесты для `BeforeConnect` / `AfterDisconnect`
- Проверить/исправить баг в `ShadowDefenderCLI` для `commit` action
- Интеграция с Go-агентом (см. `AGENT_TZ.md`)
- Мониторинг процессов (сейчас невозможен без агента)
