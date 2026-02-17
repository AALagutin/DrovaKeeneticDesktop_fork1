# Пошаговая инструкция по развёртыванию Drova Desktop Manager

## Оглавление

- [1. Требования](#1-требования)
- [2. Подготовка Windows-машин](#2-подготовка-windows-машин)
- [3. Установка на Linux-сервер](#3-установка-на-linux-сервер)
- [4. Конфигурация](#4-конфигурация)
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

### Каждая Windows-машина (игровой ПК)

- OpenSSH Server — включён и добавлен в автозагрузку
- Shadow Defender — активирован, защищён паролем
- PsExec (PsTools) — в `C:\Windows\System32` или в PATH
- Drova Esme (агент) — установлен и зарегистрирован
- Учётная запись администратора — залогинена в интерактивной сессии

---

## 2. Подготовка Windows-машин

Выполните на **каждой** Windows-машине.

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

### Проверка статуса всех воркеров

```bash
systemctl status drova_manager
```

---

## 9. Устранение неполадок

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
