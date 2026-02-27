# DrovaKeeneticDesktop — Руководство администратора

## Оглавление

1. [Обзор системы](#1-обзор-системы)
2. [Требования](#2-требования)
3. [Развёртывание](#3-развёртывание)
4. [Настройка](#4-настройка)
5. [Проверка работоспособности](#5-проверка-работоспособности)
6. [Ручной запуск](#6-ручной-запуск)
7. [Автозапуск](#7-автозапуск)
8. [Тестирование](#8-тестирование)
9. [Отладка и диагностика](#9-отладка-и-диагностика)
10. [Служебные скрипты](#10-служебные-скрипты)
11. [Ошибки и их устранение](#11-ошибки-и-их-устранение)

---

## 1. Обзор системы

**DrovaKeeneticDesktop** — Python-воркер, который работает на Linux-машине (например, роутере Keenetic) и управляет игровым Windows ПК через SSH. Интегрируется с платформой аренды Drova.io.

### Как работает

```
 Drova API (services.drova.io)
        │  polling / webhook
        ▼
 [ Linux воркер ]  ──SSH──►  [ Windows игровой ПК ]
  drova_poll / drova_socket      SSH + PsExec + Shadow Defender
```

**Жизненный цикл одной сессии аренды:**

1. Воркер стартует → запускает диагностику (проверяет ограничения, чистит реестр)
2. Ждёт появления сессии в Drova API со статусом `NEW/HANDSHAKE/ACTIVE`
3. `BeforeConnect`: входит в Shadow Defender, применяет реестровые ограничения, перезапускает explorer.exe
4. `WaitFinishOrAbort`: polling Drova API — ждёт статуса `FINISHED/ABORTED`
5. `AfterDisconnect`: выходит из Shadow Defender + перезагружает ПК (откатывает все изменения)

### Два режима работы

| Режим | Команда | Когда использовать |
|---|---|---|
| **poll** | `drova_poll` | Основной. Сам опрашивает API каждую секунду |
| **socket** | `drova_socket` | Альтернативный. Слушает TCP-порт, ждёт внешнего триггера |

---

## 2. Требования

### Linux-машина (воркер)

- Python 3.11+
- Poetry (менеджер зависимостей)
- Доступ в интернет (Drova API: `services.drova.io`)
- Сетевой доступ к Windows ПК (SSH порт 22, Drova порт 7985)

### Windows ПК (игровой)

- Включён и доступен SSH-сервер (OpenSSH Server)
- Установлен **PsExec** (из Sysinternals Suite), доступен в `PATH`
- Установлен **Shadow Defender** (`C:\Program Files\Shadow Defender\CmdTool.exe`)
- ПК зарегистрирован как сервер в личном кабинете Drova.io
- ESME-агент Drova запущен и создал ключи в реестре:
  `HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\<server_id>`

---

## 3. Развёртывание

### 3.1 Клонирование репозитория

```bash
git clone https://github.com/AALagutin/DrovaKeeneticDesktop_fork1.git
cd DrovaKeeneticDesktop_fork1

# Рабочая ветка:
git checkout claude/review-drova-keenetic-fork-qjpRj
```

### 3.2 Установка зависимостей

```bash
# Установить Poetry если нет:
curl -sSL https://install.python-poetry.org | python3 -

# Установить зависимости проекта:
poetry install
```

### 3.3 Создание файла окружения

```bash
cp .env.example .env   # если есть шаблон
# или создать вручную:
nano .env
```

Файл `.env` размещается в корне репозитория. При запуске загружается автоматически через `python-dotenv`.

Путь к `.env` можно переопределить переменной `ENV_LOCATION`:

```bash
ENV_LOCATION=/etc/drova/production.env drova_poll
```

---

## 4. Настройка

### 4.1 Переменные окружения (`.env`)

#### Режим single-host (один ПК)

```ini
# Игровой Windows ПК
WINDOWS_HOST=192.168.1.100
WINDOWS_LOGIN=Administrator
WINDOWS_PASSWORD=YourWindowsPassword

# Shadow Defender
SHADOW_DEFENDER_PASSWORD=YourSDPassword
SHADOW_DEFENDER_DRIVES=C          # диски через пробел: "C D E"

# Только для drova_socket
DROVA_SOCKET_LISTEN=7985
```

#### Режим multi-host (несколько ПК)

Вместо `.env` используется JSON-файл конфигурации:

```ini
# В .env только путь к конфигу:
DROVA_CONFIG=/etc/drova/hosts.json
SHADOW_DEFENDER_PASSWORD=DefaultSDPassword
SHADOW_DEFENDER_DRIVES=C
```

**Формат `/etc/drova/hosts.json`:**

```json
{
  "defaults": {
    "login": "Administrator",
    "password": "CommonPassword",
    "shadow_defender_password": "SDPassword",
    "shadow_defender_drives": "C"
  },
  "hosts": [
    {
      "host": "192.168.1.100"
    },
    {
      "host": "192.168.1.101",
      "login": "OtherUser",
      "password": "OtherPass"
    },
    {
      "host": "192.168.1.102",
      "login": "Admin3",
      "password": "Pass3"
    }
  ]
}
```

В multi-host режиме воркер запускает отдельный `DrovaPoll` для каждого ПК, все работают параллельно через `asyncio.gather`.

### 4.2 Параметры теней Shadow Defender

`SHADOW_DEFENDER_DRIVES` — строка с буквами дисков без разделителей:

```ini
SHADOW_DEFENDER_DRIVES=C          # только диск C
SHADOW_DEFENDER_DRIVES=CD         # диски C и D
SHADOW_DEFENDER_DRIVES=CDE        # диски C, D и E
```

### 4.3 Настройка SSH на Windows ПК

На Windows ПК должен быть установлен OpenSSH Server:

```powershell
# Установить (PowerShell от имени Администратора):
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

Убедиться, что пользователь из `WINDOWS_LOGIN` может войти по SSH с паролем `WINDOWS_PASSWORD`.

---

## 5. Проверка работоспособности

Перед первым запуском воркера проверьте всё с помощью встроенной утилиты:

```bash
poetry run drova_validate
```

Команда последовательно проверяет:
1. Наличие всех обязательных переменных в `.env`
2. SSH-подключение к Windows ПК
3. Доступность Shadow Defender CLI и корректность пароля
4. Работу SFTP (скачивает файл с ПК)
5. Работу PsExec

**Пример успешного вывода:**
```
/path/to/project/.env
Windows access complete!
Shadow Defender list is ok!
sftp open
```

**При ошибке** команда завершается с исключением и стектрейсом — проверьте соответствующий компонент.

---

## 6. Ручной запуск

### 6.1 Polling-режим (основной)

```bash
# Активировать venv и запустить:
poetry run drova_poll
```

Или через Python напрямую:

```bash
poetry run python -m drova_desktop_keenetic.bin.drova_poll
```

Воркер запускается, выводит логи в консоль и в файл `app.log` (ротируемый, 1 МБ × 5 файлов).

**Остановка:** `Ctrl+C`

### 6.2 Socket-режим

```bash
poetry run drova_socket
```

Воркер слушает порт `DROVA_SOCKET_LISTEN`. При подключении клиента (Drova Router) — проксирует соединение на порт 7985 Windows ПК и инициирует подготовку сессии.

### 6.3 Запуск с переопределением `.env`

```bash
# Использовать другой файл конфигурации:
ENV_LOCATION=/etc/drova/hosts.json poetry run drova_poll

# Или передать переменные напрямую:
WINDOWS_HOST=192.168.1.200 \
WINDOWS_LOGIN=user \
WINDOWS_PASSWORD=pass \
SHADOW_DEFENDER_PASSWORD=sdpass \
SHADOW_DEFENDER_DRIVES=C \
poetry run drova_poll
```

### 6.4 Повышение уровня логирования

Уровень логов настроен в `bin/__init__.py` как `INFO`. Для отладки без изменения кода:

```bash
# Через переменную окружения Python logging:
PYTHONPATH=. poetry run python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from drova_desktop_keenetic.bin.drova_poll import run_async_main
run_async_main()
"
```

---

## 7. Автозапуск

### 7.1 systemd (рекомендуется для Linux)

Создать unit-файл:

```bash
sudo nano /etc/systemd/system/drova-poll.service
```

**Содержимое:**

```ini
[Unit]
Description=DrovaKeenetic Poll Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=drova
Group=drova
WorkingDirectory=/opt/drova/DrovaKeeneticDesktop_fork1
ExecStart=/opt/drova/.venv/bin/drova_poll
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Переменные окружения (альтернатива .env):
# EnvironmentFile=/etc/drova/drova.env
# Environment=WINDOWS_HOST=192.168.1.100

[Install]
WantedBy=multi-user.target
```

**Применение:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable drova-poll
sudo systemctl start drova-poll
```

**Управление:**

```bash
sudo systemctl status drova-poll      # статус
sudo systemctl restart drova-poll     # перезапуск
sudo systemctl stop drova-poll        # остановка
sudo journalctl -u drova-poll -f      # логи в реальном времени
sudo journalctl -u drova-poll --since "1 hour ago"  # логи за час
```

### 7.2 Multi-host через systemd (несколько воркеров)

Для нескольких ПК лучше использовать один воркер с `DROVA_CONFIG`:

```ini
[Service]
Environment=DROVA_CONFIG=/etc/drova/hosts.json
```

Или создать отдельные unit-файлы `drova-poll@.service` с шаблоном.

### 7.3 Автозапуск на OpenWRT / Keenetic (init.d)

```bash
cat > /etc/init.d/drova_poll << 'EOF'
#!/bin/sh /etc/rc.common

START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /opt/drova/.venv/bin/drova_poll
    procd_set_param env WINDOWS_HOST=192.168.1.100 \
        WINDOWS_LOGIN=Administrator \
        WINDOWS_PASSWORD=yourpass \
        SHADOW_DEFENDER_PASSWORD=sdpass \
        SHADOW_DEFENDER_DRIVES=C
    procd_set_param respawn 3600 5 0
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
EOF

chmod +x /etc/init.d/drova_poll
/etc/init.d/drova_poll enable
/etc/init.d/drova_poll start
```

### 7.4 supervisor

```ini
[program:drova_poll]
command=/opt/drova/.venv/bin/drova_poll
directory=/opt/drova/DrovaKeeneticDesktop_fork1
user=drova
autostart=true
autorestart=true
startsecs=5
startretries=3
stderr_logfile=/var/log/drova_poll.err
stdout_logfile=/var/log/drova_poll.out
environment=WINDOWS_HOST="192.168.1.100",WINDOWS_LOGIN="Administrator",WINDOWS_PASSWORD="yourpass",SHADOW_DEFENDER_PASSWORD="sdpass",SHADOW_DEFENDER_DRIVES="C"
```

```bash
supervisorctl reread
supervisorctl update
supervisorctl start drova_poll
```

---

## 8. Тестирование

### 8.1 Запуск всех unit-тестов

```bash
poetry run pytest drova_desktop_keenetic/tests/ -v
```

### 8.2 Запуск конкретного теста

```bash
# Все тесты qwinsta:
poetry run pytest drova_desktop_keenetic/tests/test_common.py -v -k "qwinsta"

# Тест парсинга auth_code:
poetry run pytest drova_desktop_keenetic/tests/test_common.py::test_parse_RegQueryEsme -v

# С подробным выводом логов:
poetry run pytest drova_desktop_keenetic/tests/ -v -s --log-cli-level=DEBUG
```

### 8.3 Покрытые тесты

| Тест | Что проверяет |
|---|---|
| `test_parse_PSExec` | Парсинг stderr PsExec (EN и RU Windows) |
| `test_parse_RegQueryEsme` | Парсинг auth_token из реестра |
| `test_qwinsta_parse_active_session_en_bytes` | QWinSta EN, bytes |
| `test_qwinsta_parse_active_session_en_str` | QWinSta EN, str |
| `test_qwinsta_parse_active_session_ru_bytes` | QWinSta RU (Активный), bytes |
| `test_qwinsta_parse_active_session_ru_str` | QWinSta RU (Активный), str |
| `test_qwinsta_parse_active_session_none` | QWinSta — нет активной сессии |
| `test_parse_all_auth_codes` | Несколько server_id в реестре |

### 8.4 Статический анализ и форматирование

```bash
# Форматирование кода:
poetry run black drova_desktop_keenetic/
poetry run isort drova_desktop_keenetic/

# Проверка типов:
poetry run mypy drova_desktop_keenetic/
```

---

## 9. Отладка и диагностика

### 9.1 Файл логов

Логи пишутся одновременно:
- **В консоль** (stdout)
- **В файл** `app.log` в рабочей директории (ротация: 1 МБ, хранится 5 файлов)

Формат записи:
```
[2026-02-27 12:34:56] [INFO] [drova_desktop_keenetic.common.drova_poll] worker: start host=192.168.1.100
```

### 9.2 Ключевые сообщения в логах

| Сообщение | Значение |
|---|---|
| `worker: start host=X.X.X.X` | Воркер запустился для данного ПК |
| `diagnostic: start` | Началась стартовая диагностика |
| `cleanup: N server registrations found` | Найдено N записей в реестре — идёт проверка |
| `cleanup: XXXX... — invalid, deleting` | Удалена невалидная запись реестра |
| `sessions: active (ACTIVE) — diagnostic skipped` | Есть активная сессия — диагностика пропущена |
| `SD enter: OK` | Shadow Defender успешно включён |
| `SD enter: FAILED code=X` | Ошибка включения SD (неверный пароль? SD не запущен?) |
| `patch epicgames OK` | Патч Epic Games применён |
| `patch RegistryPatch FAILED` | Ошибка применения реестровых ограничений |
| `restrictions: 28/28 OK` | Все ограничения применены и верифицированы |
| `restrictions: 25/28 OK — 3 MISSING` | 3 ключа не создались — см. строки `missing:` ниже |
| `poll: session active — starting setup` | Найдена новая сессия аренды |
| `poll: ssh unreachable` | ПК недоступен по SSH (перезагружается?) |
| `poll: reboot required — running cleanup` | ESME не нашёл auth_token — ПК нужна перезагрузка |
| `poll: duplicate server registrations` | Два server_id в реестре (редкая ситуация) |
| `before_connect: done` | Все ограничения применены, сессия готова |
| `after_disconnect: SD exit+reboot` | Откат SD + перезагрузка ПК |
| `qwinsta exit_status=0 stdout=...` | Результат определения session_id (DEBUG) |
| `starting explorer.exe in session 2` | PsExec запускает explorer в нужной сессии |
| `psexec exit_status=0` | explorer.exe запущен успешно |

### 9.3 Диагностика стартовой проверки

При каждом запуске воркер автоматически:
1. Запрашивает все server_id из реестра
2. Проверяет каждый через Drova API — невалидные удаляет
3. Если нет активных сессий: входит в SD, применяет все патчи, проверяет реестр, выходит из SD + reboot

Логи диагностики выглядят так:
```
[INFO]  diagnostic: start
[INFO]  cleanup: 1 server registrations found, verifying each  ← если > 1
[INFO]  sessions: none
[INFO]  SD enter: OK — Drive C: Protected
[INFO]  patch epicgames      OK
[INFO]  patch steam          OK
[INFO]  patch ubisoft        OK
[INFO]  patch wargaming      OK
[INFO]  patch RegistryPatch  OK
[INFO]  restrictions: 28/28 OK
[INFO]  SD exit+reboot: OK
[INFO]  diagnostic: done
```

### 9.4 Проверка SSH вручную

```bash
# С Linux-машины воркера:
ssh Administrator@192.168.1.100

# Проверить qwinsta (список сессий):
ssh Administrator@192.168.1.100 qwinsta

# Проверить реестр ESME:
ssh Administrator@192.168.1.100 "reg query HKEY_LOCAL_MACHINE\\SOFTWARE\\ITKey\\Esme\\servers /s /f auth_token"

# Проверить Shadow Defender:
ssh Administrator@192.168.1.100 '& "C:\\Program Files\\Shadow Defender\\CmdTool.exe" /pwd:"yourpassword" /list /now'
```

### 9.5 Проверка Drova API вручную

```bash
# Получить auth_token из реестра (выполнить на Windows через SSH):
ssh Administrator@192.168.1.100 "reg query HKEY_LOCAL_MACHINE\\SOFTWARE\\ITKey\\Esme\\servers /s /f auth_token"

# Проверить API (подставить реальные значения):
curl -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
     -d "serveri_id=YOUR_SERVER_ID" \
     https://services.drova.io/session-manager/sessions?
```

HTTP 200 — токены валидны. HTTP 401/403 — ПК не зарегистрирован или токен устарел.

---

## 10. Служебные скрипты

### 10.1 `scripts/rollback_restrictions.ps1` — ручной откат ограничений

**Назначение:** Если Shadow Defender не выполнил откат (например, экстренная остановка воркера, ручные тесты), этот скрипт удаляет все реестровые ключи, установленные воркером.

**Запуск на Windows ПК (PowerShell от Администратора):**

```powershell
# Вариант 1 — локально на ПК:
powershell.exe -ExecutionPolicy Bypass -File "C:\scripts\rollback_restrictions.ps1"

# Вариант 2 — через SSH с Linux:
scp scripts/rollback_restrictions.ps1 Administrator@192.168.1.100:C:\\rollback.ps1
ssh Administrator@192.168.1.100 "powershell.exe -ExecutionPolicy Bypass -File C:\\rollback.ps1"
```

**Что делает скрипт:**

| Действие | Ключ реестра |
|---|---|
| Включает CMD | Удаляет `HKCU\...\System\DisableCMD` |
| Включает Task Manager | Удаляет `HKCU\...\System\DisableTaskMgr` |
| Включает VBScript | Удаляет `HKCU\...\Windows Script Host\Enabled` |
| Включает кнопку выключения | Удаляет `HKCU\...\Explorer\NoClose` |
| Включает выход из системы | Удаляет `HKCU\...\Explorer\StartMenuLogoff`, `NoLogoff` |
| Разблокирует приложения | Удаляет `HKCU\...\Explorer\DisallowRun` + список 0..16 |
| Включает gpedit, MMC | Удаляет `DisableGpedit`, `RestrictToPermittedSnapins` |
| Включает Fast User Switch | Удаляет `HKLM\...\System\HideFastUserSwitching` (требует прав Администратора) |

**Важно:** HKLM-ключи требуют запуска PowerShell от Администратора. Скрипт предупредит, если прав недостаточно.

После выполнения скрипт запускает `gpupdate /target:user /force` и советует перезапустить explorer или переlogиниться.

### 10.2 `drova_validate` — встроенная проверка конфигурации

```bash
poetry run drova_validate
```

Подробнее см. раздел [5. Проверка работоспособности](#5-проверка-работоспособности).

---

## 11. Ошибки и их устранение

### SSH недоступен: `poll: ssh unreachable`

ПК перезагружается (после AfterDisconnect) или недоступен по сети. Воркер автоматически повторяет попытку каждую секунду — это штатная ситуация.

**Если продолжается > 5 минут:**
- Проверьте питание и сеть ПК
- Проверьте, запущен ли OpenSSH Server на ПК
- `ping 192.168.1.100`

### Reboot Required: `poll: reboot required — running cleanup`

ESME-агент Drova не создал ключи в реестре (не запущен или только что установлен). Воркер инициирует AfterDisconnect (SD exit + reboot) и ждёт.

**Решение:** Убедитесь, что ESME-агент настроен на автозапуск на Windows ПК.

### Shadow Defender FAILED

```
SD enter: FAILED code=1 — Password is incorrect
```

Неверный `SHADOW_DEFENDER_PASSWORD` в `.env`. Проверьте пароль в настройках Shadow Defender на ПК.

```
SD enter: FAILED code=2
```

Shadow Defender не запущен. На Windows ПК: `services.msc` → `Shadow Defender` → Запустить и установить тип запуска «Автоматически».

### PsExec: `PsExecNotFoundExecutable`

PsExec не найден в `PATH` на Windows ПК, или имя исполняемого файла отличается.

**Решение:** Убедитесь, что `psexec.exe` доступен:

```powershell
# На Windows ПК:
where psexec
# Если не найден — скачать Sysinternals Suite и добавить в PATH
```

### Дублирование server_id: `poll: duplicate server registrations`

В реестре осталось два server_id от разных установок ESME. При следующем старте диагностика автоматически проверит оба через API и удалит невалидный.

**Ручное исправление (SSH):**

```bash
ssh Administrator@192.168.1.100 "reg query HKEY_LOCAL_MACHINE\\SOFTWARE\\ITKey\\Esme\\servers /s /f auth_token"
# Найти лишний server_id и удалить:
ssh Administrator@192.168.1.100 'reg delete "HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\INVALID-UUID" /f'
```

### Ограничения не применились: `restrictions: N/28 OK — M MISSING`

Некоторые реестровые ключи не создались. В логах ниже будут строки `missing: HKCU\...\...`.

**Причины:**
- Недостаточно прав SSH-пользователя для HKLM-ключей
- Временный сбой SSH-соединения во время патча

HKLM-ключ `HideFastUserSwitching` требует прав Администратора. Убедитесь, что `WINDOWS_LOGIN` — это пользователь с правами локального Администратора.

### Логи не создаются / `app.log` пустой

Файл `app.log` создаётся в **рабочей директории** процесса (там, откуда запущен `drova_poll`). При запуске через systemd рабочая директория задаётся `WorkingDirectory=`.

```bash
# Найти файл лога:
find /opt/drova -name "app.log" 2>/dev/null
```

---

## Быстрый старт (шпаргалка)

```bash
# 1. Установить зависимости
poetry install

# 2. Создать .env
cat > .env << EOF
WINDOWS_HOST=192.168.1.100
WINDOWS_LOGIN=Administrator
WINDOWS_PASSWORD=YourPassword
SHADOW_DEFENDER_PASSWORD=SDPassword
SHADOW_DEFENDER_DRIVES=C
EOF

# 3. Проверить конфигурацию
poetry run drova_validate

# 4. Запустить воркер
poetry run drova_poll

# 5. Следить за логами (другой терминал)
tail -f app.log
```
