# Пошаговая инструкция по развёртыванию Drova Desktop Manager

## Оглавление

- [1. Требования](#1-требования)
- [2. Подготовка Windows-машин](#2-подготовка-windows-машин)
  - [2.0 Автоматическая установка (рекомендуется)](#20-автоматическая-установка-рекомендуется)
  - [2.1 Ручная установка OpenSSH Server](#21-установка-openssh-server)
- [3. Установка на Linux-сервер](#3-установка-на-linux-сервер)
- [4. Конфигурация](#4-конфигурация)
  - [Режим A: Один ПК](#режим-a-один-пк-обратная-совместимость)
  - [Режим B: Несколько ПК](#режим-b-несколько-пк-с-общими-credentials)
  - [Режим C: JSON-конфигурация](#режим-c-json-конфигурация-разные-настройки-per-host)
  - [Раздел streaming — видеозапись сеансов](#раздел-streaming--видеозапись-сеансов)
- [5. Проверка](#5-проверка)
- [6. Запуск](#6-запуск)
- [7. Автозапуск](#7-автозапуск)
- [8. Мониторинг и логи](#8-мониторинг-и-логи)
- [9. Устранение неполадок](#9-устранение-неполадок)

---

## 1. Требования

### Linux-сервер (центральный ПК)

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| ОС | Debian 12 / Ubuntu 22.04 | Debian 13 / Ubuntu 24.04 |
| Python | 3.11+ | 3.11+ |
| RAM | 128 MB + 5 MB на каждый ПК | 512 MB (для 30 ПК) |
| Сеть | Доступ к Windows-машинам (SSH:22) | Стабильное подключение |
| Интернет | Доступ к `services.drova.io` (HTTPS:443) | — |

> **Видеозапись сеансов (опционально):** для работы раздела `streaming` дополнительно нужен RTSP-сервер (например, [MediaMTX](https://github.com/bluenviron/mediamtx)) на отдельной машине или на том же Linux-сервере. Linux-сервер должен иметь доступ к GitHub Releases для загрузки баз GeoLite2 (HTTPS:443).

### Каждая Windows-машина (игровой ПК)

- OpenSSH Server — включён и добавлен в автозагрузку
- Shadow Defender — активирован, защищён паролем
- PsExec (PsTools) — в `C:\Windows\System32` или в PATH
- Drova Esme (агент) — установлен и зарегистрирован
- Учётная запись администратора — залогинена в интерактивной сессии

> **Видеозапись сеансов (опционально):** FFmpeg установлен по пути `C:\ffmpeg\bin\ffmpeg.exe`. GPU с поддержкой аппаратного кодирования (NVIDIA NVENC, AMD AMF или Intel QSV) или любой CPU для программного кодирования (`libx264`).

---

## 2. Подготовка Windows-машин

### 2.0 Автоматическая установка (рекомендуется)

Если на каждой машине уже выполнено:

```cmd
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f
```

и сеть настроена как **Private** — можно развернуть все машины **с Linux-сервера одной командой**, без ручной работы за каждым ПК.

**Как это работает:** `scripts/deploy.py` подключается к каждому ПК по SMB (порт 445), загружает скрипт `scripts/setup_gamepc.ps1` во временную папку и запускает его через PsExec-протокол (`pypsexec`). Никакого дополнительного ПО на Windows не нужно — SMB и DCOM включены по умолчанию.

`setup_gamepc.ps1` выполняет на каждой машине:
- Устанавливает **OpenSSH Server** и переводит его в автозагрузку
- Прописывает PowerShell как оболочку по умолчанию для SSH
- Добавляет правило брандмауэра для порта 22
- Скачивает **PsExec** (Sysinternals) в `System32` и автоматически принимает EULA
- Скачивает **FFmpeg** в `C:\ffmpeg\bin\` (пропустить флагом `--skip-ffmpeg`)

#### Установка зависимостей для deploy.py

```bash
cd /opt/drova-desktop
poetry install --with setup
```

#### Запуск

```bash
# С JSON-конфигом (Режим C):
DROVA_CONFIG=/opt/drova-desktop/config.json \
    poetry run python scripts/deploy.py

# Со переменными окружения (Режим B):
WINDOWS_HOSTS=192.168.0.10,192.168.0.11,192.168.0.12 \
WINDOWS_LOGIN=Administrator WINDOWS_PASSWORD=ВашПароль \
    poetry run python scripts/deploy.py

# Без FFmpeg (быстрее, не нужен если streaming отключён):
DROVA_CONFIG=... poetry run python scripts/deploy.py --skip-ffmpeg

# Только определённые хосты из конфига:
DROVA_CONFIG=... poetry run python scripts/deploy.py --hosts 192.168.0.10,192.168.0.11
```

Пример вывода при развёртывании на 5 машин (~8 минут параллельно):

```
Deploying to 5 host(s) with parallelism=10
============================================================
[Зал1-01 / 192.168.0.10] Uploading setup script via SMB...
[Зал1-02 / 192.168.0.11] Uploading setup script via SMB...
[Зал1-03 / 192.168.0.12] Uploading setup script via SMB...
[VIP-01 / 192.168.1.10]  Uploading setup script via SMB...
[VIP-02 / 192.168.1.11]  Uploading setup script via SMB...
[Зал1-01 / 192.168.0.10] Executing (may take 5-10 min)...
...
============================================================
SUMMARY
============================================================
  [OK  ]  Зал1-01      192.168.0.10
  [OK  ]  Зал1-02      192.168.0.11
  [OK  ]  Зал1-03      192.168.0.12
  [OK  ]  VIP-01       192.168.1.10
  [FAIL]  VIP-02       192.168.1.11
         ERROR: Upload failed: Connection refused

  4/5 hosts set up successfully.
```

> **Примечание:** Shadow Defender нельзя установить автоматически (требует лицензионного GUI-установщика). Установите его вручную после автоматической настройки остальных компонентов.

---

### 2.1 Установка OpenSSH Server

Откройте PowerShell **от имени администратора**:

```powershell
# Установка
Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*' | Add-WindowsCapability -Online

# Запуск и автозагрузка
Start-Service -Name "sshd"
Set-Service -Name "sshd" -StartupType Automatic

# Проверка
Get-Service sshd
```

### 2.2 Установка Shadow Defender

1. Скачайте с [официального сайта](https://www.shadowdefender.com/)
2. Распакуйте `Setup.exe`, затем `Setupx64.exe`
3. В распакованной папке переименуйте `Setup.exe` → `zSetup.exe`
4. Запустите `zSetup.exe`, установите, перезагрузите
5. Откройте Shadow Defender → `Administration`:
   - Установите пароль через `Enable password control`
   - Снимите `Enable windows tip` (убирает плашку о shadow mode)
   - Поставьте `Need password when committing`

**Запомните пароль** — он понадобится для конфигурации.

### 2.3 Установка PsExec

1. Скачайте [PsTools](https://learn.microsoft.com/ru-ru/sysinternals/downloads/psexec)
2. Распакуйте все `.exe` файлы в `C:\Windows\System32`
3. Проверьте: откройте `cmd` и введите `psexec` — должна появиться справка

### 2.4 Проверка готовности Windows

На каждой машине убедитесь:
- Администратор залогинен (интерактивная сессия активна)
- Drova Esme запущен и зарегистрирован
- Steam / Epic Games / другие лаунчеры открыты (нужны для теста патчей)

---

## 3. Установка на Linux-сервер

### 3.1 Установка зависимостей ОС

```bash
# Debian / Ubuntu
apt update && apt install -y python3-full pipx git

# Установка poetry
pipx install poetry
```

### 3.2 Клонирование проекта

```bash
git clone https://github.com/AALagutin/DrovaKeeneticDesktop_fork1.git /opt/drova-desktop
cd /opt/drova-desktop
```

### 3.3 Установка зависимостей Python

```bash
cd /opt/drova-desktop
poetry install
```

Проверьте, что установка прошла:

```bash
poetry run python -c "import drova_desktop_keenetic; print('OK')"
```

---

## 4. Конфигурация

Поддерживается три режима конфигурации. Выберите подходящий.

### Режим A: Один ПК (обратная совместимость)

```bash
cp .env.example .env
nano .env
```

```env
WINDOWS_HOST=192.168.0.10
WINDOWS_LOGIN=Administrator
WINDOWS_PASSWORD=ВашПароль

SHADOW_DEFENDER_PASSWORD="ПарольShadowDefender"
SHADOW_DEFENDER_DRIVES="CDE"
```

| Параметр | Описание |
|----------|----------|
| `WINDOWS_HOST` | IP-адрес Windows-машины |
| `WINDOWS_LOGIN` | Логин администратора Windows |
| `WINDOWS_PASSWORD` | Пароль администратора |
| `SHADOW_DEFENDER_PASSWORD` | Пароль Shadow Defender |
| `SHADOW_DEFENDER_DRIVES` | Буквы дисков для защиты (слитно: `C`, `CD`, `CDE`) |

### Режим B: Несколько ПК с общими credentials

Все машины используют одинаковый логин/пароль (типичная конфигурация для игрового зала).

```bash
cp .env.example .env
nano .env
```

```env
WINDOWS_HOSTS=192.168.0.10,192.168.0.11,192.168.0.12,192.168.0.13,192.168.0.14

WINDOWS_LOGIN=Administrator
WINDOWS_PASSWORD=ВашПароль

SHADOW_DEFENDER_PASSWORD="ПарольShadowDefender"
SHADOW_DEFENDER_DRIVES="CDE"

POLL_INTERVAL_IDLE=5
POLL_INTERVAL_ACTIVE=3
```

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `WINDOWS_HOSTS` | — | IP-адреса через запятую |
| `POLL_INTERVAL_IDLE` | 5 | Интервал опроса API в режиме ожидания (секунды) |
| `POLL_INTERVAL_ACTIVE` | 3 | Интервал опроса API во время сессии (секунды) |

> **Совет:** для 30 ПК можно сгенерировать список IP-адресов:
> ```bash
> # Если ПК идут подряд от 192.168.0.10 до 192.168.0.39
> echo "WINDOWS_HOSTS=$(seq -s, -f '192.168.0.%.0f' 10 39)" >> .env
> ```

### Режим C: JSON-конфигурация (разные настройки per-host)

Создайте JSON-файл:

```bash
nano /opt/drova-desktop/config.json
```

```json
{
  "poll_interval_idle": 5,
  "poll_interval_active": 3,
  "defaults": {
    "login": "Administrator",
    "password": "ВашПароль",
    "shadow_defender_password": "ПарольShadowDefender",
    "shadow_defender_drives": "CDE"
  },
  "hosts": [
    {"name": "Зал1-01", "host": "192.168.0.10"},
    {"name": "Зал1-02", "host": "192.168.0.11"},
    {"name": "Зал1-03", "host": "192.168.0.12"},
    {"name": "VIP-01",  "host": "192.168.1.10", "login": "VipAdmin", "password": "ДругойПароль"},
    {"name": "VIP-02",  "host": "192.168.1.11", "shadow_defender_drives": "CD"}
  ]
}
```

В `.env` укажите путь к конфигу:

```env
DROVA_CONFIG=/opt/drova-desktop/config.json
```

Каждый хост наследует `defaults`, но может переопределить любое поле.

| Поле хоста | Обязательное | Описание |
|------------|-------------|----------|
| `host` | Да | IP-адрес или hostname |
| `name` | Нет | Имя для логов (по умолчанию `PC-01`, `PC-02`...) |
| `login` | Нет | Переопределяет `defaults.login` |
| `password` | Нет | Переопределяет `defaults.password` |
| `shadow_defender_password` | Нет | Переопределяет `defaults.shadow_defender_password` |
| `shadow_defender_drives` | Нет | Переопределяет `defaults.shadow_defender_drives` |

### Раздел streaming — видеозапись сеансов

Раздел `streaming` добавляется в JSON-конфигурацию (Режим C). Доступен только через JSON — через переменные окружения не поддерживается.

**Принцип работы:** при начале каждого игрового сеанса Linux-сервер запускает FFmpeg на Windows-машине через PsExec по SSH. FFmpeg захватывает экран (`gdigrab`) и стримит по RTSP на монитор-сервер. Поверх видео накладывается оверлей: IP клиента, город/провайдер/ASN (GeoIP), название игры, время сеанса и живые часы. После окончания сеанса FFmpeg останавливается через `taskkill`.

GeoIP определяется в два шага:
1. Локальная база MaxMind GeoLite2 (скачивается с GitHub автоматически, обновляется раз в `geoip_update_interval_days` дней).
2. Если база недоступна — запрос к `ip-api.com`.

**Пример конфигурации:**

```json
{
  "poll_interval_idle": 5,
  "poll_interval_active": 3,
  "defaults": {
    "login": "Administrator",
    "password": "ВашПароль",
    "shadow_defender_password": "ПарольShadowDefender",
    "shadow_defender_drives": "CDE"
  },
  "hosts": [
    {"name": "Зал1-01", "host": "192.168.0.10"},
    {"name": "Зал1-02", "host": "192.168.0.11"}
  ],
  "streaming": {
    "enabled": true,
    "monitor_ip": "192.168.1.200",
    "monitor_port": 8554,
    "fps": 2,
    "resolution": "1280x720",
    "bitrate": "200k",
    "ffmpeg_path": "C:\\ffmpeg\\bin\\ffmpeg.exe",
    "encoder": "h264_nvenc",
    "encoder_preset": "p1",
    "process_priority": "LOW",
    "geoip_db_dir": "geoip_db",
    "geoip_update_interval_days": 7
  }
}
```

**Описание параметров:**

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `enabled` | `false` | Включить видеозапись сеансов |
| `monitor_ip` | `""` | IP-адрес RTSP-сервера (MediaMTX или аналог) |
| `monitor_port` | `8554` | Порт RTSP-сервера |
| `fps` | `2` | Частота кадров захвата (кадр/с). `2` — баланс нагрузки и читаемости |
| `resolution` | `"1280x720"` | Разрешение выходного потока |
| `bitrate` | `"200k"` | Целевой битрейт (CBR). Примеры: `100k`, `500k`, `1M` |
| `ffmpeg_path` | `C:\ffmpeg\bin\ffmpeg.exe` | Полный путь к `ffmpeg.exe` на Windows-машине |
| `encoder` | `"h264_nvenc"` | Видеокодек: `h264_nvenc` (NVIDIA), `h264_amf` (AMD), `h264_qsv` (Intel), `libx264` (CPU) |
| `encoder_preset` | `"p1"` | Пресет кодека. `p1`–`p7` для NVENC (p1 — быстрейший); `ultrafast` для libx264 |
| `process_priority` | `"LOW"` | Приоритет процесса FFmpeg: `LOW`, `BELOWNORMAL`, `NORMAL` |
| `geoip_db_dir` | `"geoip_db"` | Директория для хранения баз GeoLite2 (относительно рабочего каталога) |
| `geoip_update_interval_days` | `7` | Интервал автообновления баз GeoLite2 (дни) |

**Поток RTSP** формируется по шаблону:
```
rtsp://<monitor_ip>:<monitor_port>/live/<pc-ip-через-дефис>
```

Например, для ПК `192.168.0.10`:
```
rtsp://192.168.1.200:8554/live/192-168-0-10
```

**Минимальная настройка MediaMTX на Linux:**

```bash
# Установка
wget https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_amd64.tar.gz
tar -xzf mediamtx_linux_amd64.tar.gz
./mediamtx &
```

MediaMTX слушает RTSP на порту `8554` по умолчанию. Просмотр потоков через VLC или `ffplay`:

```bash
ffplay rtsp://192.168.1.200:8554/live/192-168-0-10
```

---

## 5. Проверка

### 5.1 Проверка единичного подключения

```bash
cd /opt/drova-desktop
poetry run drova_validate
```

Успешный вывод:
```
/opt/drova-desktop/.env
Windows access complete!
Shadow Defender list is ok!
sftp open
Ok!
```

> **Примечание:** `drova_validate` проверяет подключение к одному хосту из `WINDOWS_HOST`.
> Для проверки всех хостов в multi-PC режиме используйте ручную проверку SSH (см. п. 5.2).

### 5.2 Ручная проверка SSH ко всем машинам

```bash
# Проверить доступность каждой машины
for ip in 192.168.0.10 192.168.0.11 192.168.0.12; do
    echo -n "$ip: "
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no Administrator@$ip "echo OK" 2>/dev/null || echo "FAIL"
done
```

### 5.3 Тестовый запуск

```bash
cd /opt/drova-desktop
poetry run drova_poll
```

Должны появиться логи вида:
```
INFO  Starting DrovaManager with 5 host(s)
INFO  Worker[Зал1-01] Started polling
INFO  Worker[Зал1-02] Started polling
INFO  Worker[Зал1-03] Started polling
INFO  Worker[VIP-01] Started polling
INFO  Worker[VIP-02] Started polling
```

Остановка: `Ctrl+C`

---

## 6. Запуск

### Ручной запуск (foreground)

```bash
cd /opt/drova-desktop
poetry run drova_poll
```

Процесс работает в текущем терминале. `Ctrl+C` для остановки.

### Запуск в фоне (без systemd)

```bash
cd /opt/drova-desktop
nohup poetry run drova_poll > /var/log/drova-poll.log 2>&1 &
echo $! > /var/run/drova-poll.pid
```

---

## 7. Автозапуск

### Вариант A: systemd (рекомендуется для Debian / Ubuntu)

**Для multi-PC режима** (один сервис на все ПК):

```bash
# Создать ссылку на сервис
ln -s /opt/drova-desktop/systemd/drova_manager.service /etc/systemd/system/drova_manager.service

# Перезагрузить systemd
systemctl daemon-reload

# Запустить
systemctl start drova_manager

# Проверить статус
systemctl status drova_manager

# Добавить в автозагрузку
systemctl enable drova_manager
```

**Для single-PC режима** (совместимость со старой конфигурацией):

```bash
# Создать ссылку
ln -s /opt/drova-desktop/systemd/drova_poll@.service /etc/systemd/system/drova_poll@.service
systemctl daemon-reload

# Создать файл i9_3080ti.env с настройками одного ПК
cp .env.example i9_3080ti.env
nano i9_3080ti.env

# Запустить
systemctl start drova_poll@i9_3080ti
systemctl enable drova_poll@i9_3080ti
```

### Вариант B: Entware / init.d (для Keenetic / OpenWrt)

```bash
# Создать сервис
touch /etc/init.d/drova_poll.gaming_hall
chmod +x /etc/init.d/drova_poll.gaming_hall
```

Содержимое файла:

```bash
#!/bin/bash
ENV_LOCATION=/opt/drova-desktop/.env
. /opt/drova-desktop/init.d/drova_poll "$@"
```

Запуск:

```bash
/etc/init.d/drova_poll.gaming_hall start
```

---

## 8. Мониторинг и логи

### Просмотр логов в реальном времени

```bash
# systemd
journalctl -u drova_manager -f

# Или с фильтром по конкретному ПК
journalctl -u drova_manager -f | grep "Worker\[Зал1-01\]"
```

### Формат логов

```
INFO  Worker[Зал1-01] Started polling
INFO  Worker[Зал1-01] Checking for active desktop session
INFO  Worker[Зал1-01] Desktop session detected - applying patches
WARN  Worker[Зал1-01] Some patches failed, but continuing with session
INFO  Worker[Зал1-01] Waiting for session to finish
INFO  Worker[Зал1-01] Session finished - exiting shadow defender and rebooting
DEBUG Worker[Зал1-01] Cannot connect - PC unavailable or rebooting
INFO  Worker[Зал1-01] Started polling
```

**Логи видеозаписи (если `streaming.enabled = true`):**

```
INFO  BeforeConnect Resolving GeoIP for client 95.173.1.1
DEBUG geoip GeoIP local miss for 95.173.1.1, falling back to ip-api.com
INFO  BeforeConnect Starting FFmpeg stream: rtsp://192.168.1.200:8554/live/192-168-0-10
INFO  AfterDisconnect Stopping FFmpeg stream
WARN  geoip GeoIP: API lookup failed for 95.173.1.1   ← ip-api.com недоступен, оверлей без гео
WARN  geoip GeoIP: failed to download databases — will use API fallback
INFO  geoip GeoIP databases updated successfully
```

### Проверка статуса всех воркеров

```bash
systemctl status drova_manager
```

---

## 9. Устранение неполадок

### Ошибки deploy.py (автоматическая установка)

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `pypsexec not installed` | Группа `setup` не установлена | `poetry install --with setup` |
| `Upload failed: Connection refused` | SMB (порт 445) недоступен | Проверьте, что брандмауэр Windows не блокирует порт 445; убедитесь что `LocalAccountTokenFilterPolicy=1` |
| `Upload failed: STATUS_LOGON_FAILURE` | Неверные учётные данные | Проверьте `WINDOWS_LOGIN` / `WINDOWS_PASSWORD` |
| `Execution failed: timed out` | Скрипт выполняется дольше 10 минут | Перезапустите с `--skip-ffmpeg`; или увеличьте `EXEC_TIMEOUT_SECONDS` в `deploy.py` |
| `[FAIL] ... Add-WindowsCapability error` | Windows Update недоступен | Убедитесь что ПК имеет доступ к интернету; или установите OpenSSH вручную (п. 2.1) |
| `EULA error` для PsExec | EULA не принята от имени SYSTEM | Уже обрабатывается скриптом (пишет оба ключа HCU и HKLM); если повторяется — запустите PsExec вручную один раз |

### Ошибки запуска

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `KeyError: 'WINDOWS_HOST'` | Не задан `WINDOWS_HOST` или `WINDOWS_HOSTS` | Проверьте `.env` файл |
| `ModuleNotFoundError` | Зависимости не установлены | `cd /opt/drova-desktop && poetry install` |
| `No module named 'dotenv'` | Poetry venv не активировано | Используйте `poetry run drova_poll` |

### Ошибки подключения

| Лог | Причина | Решение |
|-----|---------|---------|
| `Cannot connect - PC unavailable or rebooting` | Windows выключен или перезагружается | Нормально — воркер переподключится автоматически |
| `Reboot required` | Drova Esme не записал auth_token в реестр | Проверьте что Esme запущен на Windows |
| `Unexpected error in polling cycle` | Непредвиденная ошибка | Смотрите полный traceback в `journalctl` |

### Ошибки патчей

| Лог | Причина | Решение |
|-----|---------|---------|
| `Patch failed: epicgames` | Файл GameUserSettings.ini отсутствует | Запустите Epic Games хотя бы раз на Windows |
| `Patch failed: steam` | Файл loginusers.vdf отсутствует | Запустите Steam хотя бы раз на Windows |
| `Failed patches: [...]` | Один или несколько патчей не применились | Сессия продолжится, но лаунчер может остаться залогиненным |
| `Shadow Defender: not correct` | Неверный пароль Shadow Defender | Проверьте `SHADOW_DEFENDER_PASSWORD` |

### Ошибки видеозаписи (streaming)

| Лог | Причина | Решение |
|-----|---------|---------|
| `Starting FFmpeg stream` — поток не появляется в MediaMTX | FFmpeg не запустился | Проверьте `ffmpeg_path` в конфиге; убедитесь что `ffmpeg.exe` существует на Windows |
| `Streaming enabled but session/geoip_client not provided` | Внутренняя ошибка конфигурации | Обновите пакет; проверьте что `app_config` передаётся воркеру |
| `GeoIP: failed to download databases` | Linux-сервер не может достучаться до GitHub | Проверьте HTTPS-доступ наружу; GeoIP автоматически вернётся к ip-api.com |
| `GeoIP: API lookup failed` | `ip-api.com` недоступен | Оверлей отобразится без города/провайдера; это не критично |
| Поток зависает при просмотре | Низкая пропускная способность сети | Уменьшите `bitrate` или `fps`; понизьте `resolution` |
| `ffmpeg.exe` удалён пользователем во время сессии | Пользователь удалил файл | `AfterDisconnect` использует `taskkill` — если файл удалён, процесс уже завершён |
| Высокая нагрузка на GPU во время сессии | FFmpeg работает без ограничения FPS | Уменьшите `fps` до `1`; используйте `process_priority: LOW` |

**Ручная проверка RTSP-потока:**

```bash
ffplay rtsp://192.168.1.200:8554/live/192-168-0-10
# или
vlc rtsp://192.168.1.200:8554/live/192-168-0-10
```

**Список активных RTSP-потоков** (через API MediaMTX):

```bash
curl http://192.168.1.200:9997/v3/paths/list | python3 -m json.tool
```

### Как перезапустить

```bash
# Мягкий перезапуск (дождётся завершения текущих сессий)
systemctl restart drova_manager

# Проверить что запустился
systemctl status drova_manager
journalctl -u drova_manager --since "1 min ago"
```

### Как обновить

```bash
cd /opt/drova-desktop
git pull
poetry install
systemctl restart drova_manager
```
