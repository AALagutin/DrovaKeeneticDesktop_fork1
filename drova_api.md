# Drova API — Карта методов

**Base URL:** `https://services.drova.io`

**Аутентификация:** все защищённые эндпоинты принимают заголовок:
```
X-Auth-Token: <token>
```
Токен получают из QR-кода в личном кабинете Drova, из Windows-реестра (`HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers`) или из файла `token.json`.

Многие эндпоинты дополнительно принимают query-параметр `user_id` (UUID мерчанта), читаемый из реестра по пути `HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\{server_id}` → значение `user_id`.

---

## Оглавление

| # | Сервис | Метод | Эндпоинт | Auth |
|---|--------|-------|----------|------|
| 1 | accounting | GET | [`/accounting/myaccount`](#1-get-accountingmyaccount) | ✅ |
| 2 | token-verifier | POST | [`/token-verifier/renewProxyToken`](#2-post-token-verifierrenewproxytoken) | ❌ |
| 3 | session-manager | GET | [`/session-manager/sessions`](#3-get-session-managersessions) | ✅ |
| 4 | server-manager | GET | [`/server-manager/servers`](#4-get-server-managerservers) | ✅ |
| 5 | server-manager | GET | [`/server-manager/servers/{server_id}`](#5-get-server-managerserversserver_id) | ✅ |
| 6 | server-manager | POST | [`/server-manager/servers/{server_id}/set_published/{value}`](#6-post-server-managerserversserver_idset_publishedvalue) | ✅ |
| 7 | server-manager | GET | [`/server-manager/serverproduct/list4edit2/{server_id}`](#7-get-server-managerserverproductlist4edit2server_id) | ✅ |
| 8 | server-manager | GET | [`/server-manager/serverendpoint/list/{server_id}`](#8-get-server-managerserverendpointlistserver_id) | ✅ |
| 9 | server-manager | GET | [`/server-manager/servers/server_names`](#9-get-server-managerserversserver_names) | ✅ |
| 10 | server-manager | POST | [`/server-manager/servers/public/web`](#10-post-server-managerserverspublicweb) | ❌ |
| 11 | server-manager | GET | [`/server-manager/product/get/{product_id}`](#11-get-server-managerproductgetproduct_id) | ✅ |
| 12 | product-manager | GET | [`/product-manager/product/listfull2`](#12-get-product-managerproductlistfull2) | ❌ |
| 13 | accounting | GET | [`/accounting/statistics/most_popular_games`](#13-get-accountingstatisticsmost_popular_games) | ❌ |
| 14 | accounting | GET | [`/accounting/statistics/myserverusageprepared`](#14-get-accountingstatisticsmyserverusageprepared) | ✅ |
| 15 | accounting | GET | [`/accounting/unpayedstats/{user_id}`](#15-get-accountingunpayedstatsuser_id) | ✅ |
| 16 | geo | GET | [`/geo/byprefix`](#16-get-geobyprefix) | ❌ |
| 17 | server-manager | GET | [`/server-manager/serverproduct/list4edit2/{server_id}/{product_id}`](#17-get-server-managerserverproductlist4edit2server_idproduct_id) | ✅ |
| 18 | server-manager | POST | [`/server-manager/serverproduct/add/{server_id}/{product_id}`](#18-post-server-managerserverproductaddserver_idproduct_id) | ✅ |
| 19 | server-manager | POST | [`/server-manager/serverproduct/set_enabled/{server_id}/{product_id}/{value}`](#19-post-server-managerserverproductset_enabledserver_idproduct_idvalue) | ✅ |
| 20 | server-manager | POST | [`/server-manager/serverproduct/update`](#20-post-server-managerserverproductupdate) | ✅ |

---

## 1. GET /accounting/myaccount

Получить информацию об аккаунте текущего пользователя.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Параметры:** нет

**Пример ответа:**
```json
{
  "uuid": "11111111-2222-3333-4444-555555555555",
  "name": "ИмяПользователя"
}
```

**Пример использования** ([drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1), `api.py`):
```python
BASE_URL = "https://services.drova.io"

def get_account_info(token: str):
    resp = requests.get(
        f"{BASE_URL}/accounting/myaccount",
        headers={"X-Auth-Token": token}
    )
    return resp.json(), resp.status_code

# Использование в боте (bot.py):
accountInfo, status = get_account_info(token)
if status == 200:
    user_id = accountInfo['uuid']
    username = accountInfo['name']
```

---

## 2. POST /token-verifier/renewProxyToken

Обновить (продлить) прокси-токен. Возвращает новый токен. Не требует аутентификации — старый токен передаётся в теле запроса.

**Заголовки:** нет

**Тело запроса (JSON):**
```json
{
  "proxy_token": "<текущий_токен>"
}
```

**Пример ответа:**
```json
{
  "proxyToken": "<новый_токен>",
  "verificationStatus": "success",
  "client_id": "11111111-2222-3333-4444-555555555555",
  "client_roles": ["client", "merchant"],
  "server_id": null,
  "session_id": null
}
```

**Пример использования** ([drova-vm-watch_fork1](https://github.com/AALagutin/drova-vm-watch_fork1), `utils_api.py`):
```python
RENEWAL_ENDPOINT = "https://services.drova.io/token-verifier/renewProxyToken"
AUTH_TOKEN = None  # загружается из token.json

def request_token_renewal():
    global AUTH_TOKEN
    r = requests.post(RENEWAL_ENDPOINT, json={"proxy_token": AUTH_TOKEN}, timeout=5)
    r.raise_for_status()
    data = r.json()
    new_token = data.get("proxyToken")
    if new_token:
        AUTH_TOKEN = new_token
        HEADERS["X-Auth-Token"] = AUTH_TOKEN
        with open("token.json", "w") as f:
            json.dump({"auth_token": AUTH_TOKEN}, f)
```

Метод вызывается автоматически при получении `401 Unauthorized` от любого другого эндпоинта.

---

## 3. GET /session-manager/sessions

Получить список сессий (игровых сеансов). Поддерживает фильтрацию по серверу, статусу, мерчанту; поддерживает пагинацию.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Query-параметры (все опциональны):**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `server_id` | string (UUID) | Фильтр по станции |
| `state` | string | Фильтр по статусу; можно передавать несколько раз (`state=NEW&state=HANDSHAKE`). В коде дашборда встречается также вариант `status` |
| `limit` | integer | Максимальное число сессий в ответе |
| `merchant_id` | string (UUID) | Фильтр по мерчанту |

**Статусы сессии:** `NEW`, `HANDSHAKE`, `ACTIVE`, `ABORTED`, `FINISHED`

**Пример ответа:**
```json
{
  "sessions": [
    {
      "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "id": 12345,
      "product_id": "ffffffff-0000-1111-2222-333333333333",
      "client_id": "44444444-5555-6666-7777-888888888888",
      "server_id": "99999999-aaaa-bbbb-cccc-dddddddddddd",
      "created_on": 1700000000000,
      "finished_on": null,
      "status": "ACTIVE",
      "creator_ip": "1.2.3.4",
      "abort_comment": null,
      "score": null,
      "score_reason": null,
      "score_text": null,
      "billing_type": "TIME"
    }
  ]
}
```

### Примеры использования

**[DrovaKeeneticDesktop_fork1](https://github.com/AALagutin/DrovaKeeneticDesktop_fork1)** (`drova.py`) — async Python (aiohttp):
```python
URL_SESSIONS = "https://services.drova.io/session-manager/sessions?"

# Последняя сессия по серверу
async def get_latest_session(server_id: str, auth_token: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            URL_SESSIONS,
            data={"serveri_id": server_id},
            headers={"X-Auth-Token": auth_token}
        ) as resp:
            data = SessionsResponse(**await resp.json())
            return data.sessions[0] if data.sessions else None

# Только новые / рукопожатные сессии
async def get_new_session(server_id: str, auth_token: str):
    query_params = "state=NEW&state=HANDSHAKE"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            URL_SESSIONS + query_params,
            data={"serveri_id": server_id},
            headers={"X-Auth-Token": auth_token}
        ) as resp:
            data = SessionsResponse(**await resp.json())
            return data.sessions[0] if data.sessions else None
```

> ⚠️ **Опечатка в репозитории:** параметр передаётся как `data={"serveri_id": server_id}` (лишняя `i`) через aiohttp `data=` вместо `params=`. В реальных запросах этот параметр, вероятно, не уходит в URL — фактически возвращаются все сессии без фильтра по серверу.

**[drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1)** (`api.py`) — sync Python (requests):
```python
def get_sessions(auth_token, *, merchant_id=None, server_id=None, limit=None):
    params = {}
    if server_id:
        params["server_id"] = server_id
    if limit:
        params["limit"] = limit
    if merchant_id:
        params["merchant_id"] = merchant_id
    return _get("/session-manager/sessions", params=params,
                headers={"X-Auth-Token": auth_token})

# Последняя сессия на станции:
data, _ = get_sessions(auth_token, server_id=server_uuid, limit=1)
session = data["sessions"][0]

# Все сессии для экспорта:
data, _ = get_sessions(auth_token, server_id=server_uuid)
sessions = data["sessions"]
```

**[drova-vm-watch_fork1](https://github.com/AALagutin/drova-vm-watch_fork1)** (`utils_api.py`) — фильтр по нескольким статусам:
```python
SESSIONS_ENDPOINT = "https://services.drova.io/session-manager/sessions"

def get_last_session_status(statuses=("ACTIVE", "HANDSHAKE", "NEW")):
    params = [("status", s) for s in statuses]
    params.append(("server_id", SERVER_UUID))
    params.append(("limit", "2"))
    r = safe_request("GET", SESSIONS_ENDPOINT, params=params)
    sessions = r.json().get("sessions", [])
    if not sessions:
        return "INACTIVE"
    return sessions[0].get("status")
# URL: /session-manager/sessions?status=ACTIVE&status=HANDSHAKE&status=NEW&server_id=...&limit=2
```

**[Drova-Session-INFO_Fork1](https://github.com/AALagutin/Drova-Session-INFO_Fork1)** (`main.go`) — Go:
```go
url2 := "https://services.drova.io/session-manager/sessions"
req, _ := http.NewRequest("GET", url2, nil)
q := req.URL.Query()
q.Add("server_id", serverID)
req.URL.RawQuery = q.Encode()
req.Header.Set("X-Auth-Token", authToken)
resp, _ := client.Do(req)

type SessionsData struct {
    Sessions []struct {
        Id          int32
        Uuid        string
        Client_id   string
        Server_id   string
        Product_id  string
        Created_on  int64
        Finished_on int64
        Status      string
        Creator_ip  string
        Billing_type string
    }
}
```

**[drova-vm-watch_fork1 (userscript)](https://github.com/AALagutin/drova-vm-watch_fork1)** — JS-перехват с принудительным limit=1000:
```javascript
const SESSIONS_RE = /\/session-manager\/sessions(?:\?|$)/i;

function rewriteSessionsLimit(urlLike) {
    const u = new URL(String(urlLike), location.href);
    if (!SESSIONS_RE.test(u.pathname)) return null;
    if (u.searchParams.get('limit') !== '1000') {
        u.searchParams.set('limit', '1000');
        return u.href;
    }
    return null;
}
```

**[DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1)** (`main.go`, `sessionInfo.go`) — Go, токен из Windows-реестра, `creator_ip` используется для геолокации игрока:
```go
const UrlSessions = "https://services.drova.io/session-manager/sessions"

// Единая функция для всех Drova-запросов:
func getFromURL(url, cell, IDinCell string) (responseString string, err error) {
    _, err = http.Get("https://services.drova.io") // проверка доступности
    if err != nil {
        return
    }
    client := &http.Client{}
    req, _ := http.NewRequest("GET", url, nil)
    q := req.URL.Query()
    q.Add(cell, IDinCell) // cell="server_id", IDinCell=<serverID>
    req.URL.RawQuery = q.Encode()
    req.Header.Set("X-Auth-Token", authToken)
    resp, _ := client.Do(req)
    // ...
    return
}

// Структуры ответа:
type SessionsData struct {
    Sessions []struct {
        Session_uuid  string `json:"uuid"`
        Product_id    string `json:"product_id"`
        Created_on    int64  `json:"created_on"`
        Finished_on   int64  `json:"finished_on"`
        Status        string `json:"status"`
        Creator_ip    string `json:"creator_ip"`   // IP игрока — передаётся в ipinfo.io
        Abort_comment string `json:"abort_comment"`
        Score         int64  `json:"score"`
        ScoreReason   int64  `json:"score_reason"`
        Comment       string `json:"score_text"`
        Billing_type  string `json:"billing_type"`
    }
}

// Токен и server_id из реестра Windows:
regFolder := `SOFTWARE\ITKey\Esme`
serverID   = regGet(regFolder, "last_server")
authToken  = regGet(regFolder+`\servers\`+serverID, "auth_token")
```

> В V2 IP игрока берётся из поля `creator_ip` ответа API — в отличие от V1, где он захватывался через TCP-порт 7990.

---

## 4. GET /server-manager/servers

Получить список станций (серверов) мерчанта.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `user_id` | string (UUID) | UUID мерчанта (необязателен, но обычно передаётся) |

**Пример ответа:**
```json
[
  {
    "uuid": "99999999-aaaa-bbbb-cccc-dddddddddddd",
    "name": "Станция 1",
    "state": "IDLE",
    "published": true,
    "city_name": "Москва",
    "user_id": "11111111-2222-3333-4444-555555555555",
    "groups_list": []
  }
]
```

**Поля `state`:** `IDLE`, `BUSY`, `HANDSHAKE`, `OFFLINE` и др.

### Примеры использования

**[drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1)** (`api.py`):
```python
def get_servers(auth_token: str, user_id: str):
    return _get("/server-manager/servers",
                params={"user_id": user_id},
                headers={"X-Auth-Token": auth_token})

servers, status = get_servers(auth_token, user_id)
for s in servers:
    print(s['uuid'], s['name'], s['state'], s['published'])
```

**[Drova-Session-INFO_Fork1](https://github.com/AALagutin/Drova-Session-INFO_Fork1)** (`main.go`):
```go
url1 := "https://services.drova.io/server-manager/servers"
req, _ := http.NewRequest("GET", url1, nil)
req.Header.Set("X-Auth-Token", authToken)
resp, _ := client.Do(req)

type serverManager []struct {
    Uuid    string
    Name    string
    User_id string
}
```

---

## 5. GET /server-manager/servers/{server_id}

Получить детальную информацию об одной станции по её UUID.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Параметры:** нет (server_id — в пути)

**Пример ответа:**
```json
{
  "uuid": "99999999-aaaa-bbbb-cccc-dddddddddddd",
  "name": "Станция 1",
  "state": "BUSY",
  "published": true
}
```

**Пример использования** ([drova-vm-watch_fork1](https://github.com/AALagutin/drova-vm-watch_fork1), `utils_api.py`):
```python
SERVER_UUID = "99999999-aaaa-bbbb-cccc-dddddddddddd"  # из .env
SERVER_ENDPOINT = f"https://services.drova.io/server-manager/servers/{SERVER_UUID}"

def get_station_status():
    r = safe_request("GET", SERVER_ENDPOINT)
    return r.json().get("state")

def get_station_published():
    r = safe_request("GET", SERVER_ENDPOINT)
    return r.json().get("published")
```

---

## 6. POST /server-manager/servers/{server_id}/set_published/{value}

Опубликовать или снять с публикации станцию. Тело запроса пустое.

> ⚠️ **Внимание:** согласно комментариям в коде, семантика **инвертирована**:
> - `/set_published/true` → **убирает** станцию из публичного каталога (приват)
> - `/set_published/false` → **публикует** станцию в каталоге

**Заголовки:**
```
X-Auth-Token: <token>
```

**Тело запроса:** пустое

**Пример использования** ([drova-vm-watch_fork1](https://github.com/AALagutin/drova-vm-watch_fork1), `utils_api.py`):
```python
VISIBILITY_ENDPOINT = f"https://services.drova.io/server-manager/servers/{SERVER_UUID}/set_published/"

def set_station_published(published: bool):
    # True → unpublish (private), False → publish
    url = VISIBILITY_ENDPOINT + ("true" if published else "false")
    r = safe_request("POST", url)
    # пустой POST .../set_published/true  — убрать сервер в приват
    # пустой POST .../set_published/false — опубликовать сервер
```

---

## 7. GET /server-manager/serverproduct/list4edit2/{server_id}

Получить список всех продуктов (игр), настроенных на конкретной станции, с возможностью редактирования. Показывает статус включённости/публикации каждой игры.

> Для получения конфигурации одной конкретной игры на станции используйте вариант с двумя path-параметрами: [`/server-manager/serverproduct/list4edit2/{server_id}/{product_id}`](#17-get-server-managerserverproductlist4edit2server_idproduct_id) (эндпоинт 17).

**Заголовки:**
```
X-Auth-Token: <token>
```

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `user_id` | string (UUID) | UUID мерчанта |

**Пример ответа:**
```json
[
  {
    "productId": "ffffffff-0000-1111-2222-333333333333",
    "title": "Cyberpunk 2077",
    "enabled": true,
    "published": true,
    "available": true
  }
]
```

**Пример использования** ([drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1), `api.py`):
```python
def get_server_products(auth_token: str, user_id: str, server_id: str):
    path = f"/server-manager/serverproduct/list4edit2/{server_id}"
    return _get(path, params={"user_id": user_id},
                headers={"X-Auth-Token": auth_token})

# Найти неактивные продукты:
products, _ = get_server_products(auth_token, user_id, server_uuid)
for product in products:
    if not product.get('published') or not product.get('enabled') or not product.get('available'):
        print(f"Отключён: {product['title']}")

# Получить ID продукта по названию:
product_id = product['productId']
```

---

## 8. GET /server-manager/serverendpoint/list/{server_id}

Получить список сетевых эндпоинтов (IP-адресов и портов) станции.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `server_id` | string (UUID) | UUID станции (дублируется и в пути, и в параметрах) |
| `limit` | integer | Максимальное число эндпоинтов |

**Пример ответа:**
```json
[
  {
    "ip": "192.168.1.100",
    "base_port": 7000
  },
  {
    "ip": "1.2.3.4",
    "base_port": 7000
  }
]
```

**Пример использования** ([drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1), `api.py`):
```python
def get_server_endpoints(auth_token: str, server_id: str, *, limit=None):
    params = {"server_id": server_id}
    if limit:
        params["limit"] = limit
    path = f"/server-manager/serverendpoint/list/{server_id}"
    return _get(path, params=params, headers={"X-Auth-Token": auth_token})

# Разделить IP на внутренние и внешние:
ips, _ = get_server_endpoints(auth_token, server_uuid, limit=1)
for endpoint in ips:
    if isRfc1918Ip(endpoint['ip']):
        internal.append(endpoint)
    else:
        external.append(endpoint)
print(f"IP: {endpoint['ip']}:{endpoint['base_port']}")
```

---

## 9. GET /server-manager/servers/server_names

Получить словарь `server_id → name` для всех серверов. Используется веб-дашбордом Drova и перехватывается пользовательскими скриптами.

**Заголовки:** сессионная аутентификация дашборда (cookie)

**Параметры:** нет

**Пример ответа:**
```json
{
  "99999999-aaaa-bbbb-cccc-dddddddddddd": "Станция 1",
  "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": "Станция 2"
}
```

**Пример использования** ([drova-vm-watch_fork1 userscript](https://github.com/AALagutin/drova-vm-watch_fork1), `simpletable.js`):
```javascript
const NAMES_RE = /\/server-manager\/servers\/server_names(?:\?|$)/i;

// Перехват XHR/fetch дашборда:
if (NAMES_RE.test(url)) {
    const data = await response.json();
    // data: { "<uuid>": "Имя станции", ... }
    for (const [uuid, name] of Object.entries(data)) {
        stationNames[uuid] = name;
    }
}
```

---

## 10. POST /server-manager/servers/public/web

Публичный эндпоинт для получения списка всех опубликованных станций. Аутентификация не требуется. Поддерживает фильтрацию и пагинацию.

**Заголовки:** нет

**Тело запроса (JSON):**
```json
{
  "stationNameOrDescription": null,
  "stationStatus": null,
  "products": [],
  "geo": null,
  "requiredAccount": null,
  "freeToPlay": null,
  "license": null,
  "limit": 1000,
  "offset": 0,
  "published": true
}
```

**Поля тела запроса:**

| Поле | Тип | Описание |
|------|-----|----------|
| `stationNameOrDescription` | string\|null | Поиск по имени или описанию |
| `stationStatus` | string\|null | Фильтр по статусу станции |
| `products` | array | Список UUID продуктов для фильтрации |
| `geo` | object\|null | Гео-фильтр |
| `requiredAccount` | bool\|null | Требуется аккаунт |
| `freeToPlay` | bool\|null | Только бесплатные |
| `license` | string\|null | Тип лицензии |
| `limit` | integer | Лимит (до 1000) |
| `offset` | integer | Смещение для пагинации |
| `published` | bool | Только опубликованные |

**Пример ответа:**
```json
[
  {
    "uuid": "99999999-aaaa-bbbb-cccc-dddddddddddd",
    "name": "Станция 1",
    "city_name": "Москва"
  }
]
```

**Пример использования** ([drova-dash](https://github.com/AALagutin/drova-dash), `streamlit_app.py`):
```python
STATIONS_URL = "https://services.drova.io/server-manager/servers/public/web"

@st.cache_data(show_spinner=False, ttl=600)
def fetch_stations_dict(limit=1000, offset=0):
    payload = {
        "stationNameOrDescription": None,
        "stationStatus": None,
        "products": [],
        "geo": None,
        "requiredAccount": None,
        "freeToPlay": None,
        "license": None,
        "limit": limit,
        "offset": offset,
        "published": True,
    }
    r = requests.post(STATIONS_URL, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    uuid_to_name = {}
    uuid_to_city = {}
    for item in data:
        uuid_to_name[item["uuid"]] = item.get("name")
        uuid_to_city[item["uuid"]] = item.get("city_name")
    return uuid_to_name, uuid_to_city
```

---

## 11. GET /server-manager/product/get/{product_id}

Получить детальную информацию о продукте (игре) на сервере, включая пути установки и аргументы запуска.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Параметры:** `product_id` — UUID продукта в пути URL

**Пример ответа:**
```json
{
  "product_id": "ffffffff-0000-1111-2222-333333333333",
  "title": "Cyberpunk 2077",
  "game_path": "C:\\Games\\Cyberpunk2077\\bin\\x64\\Cyberpunk2077.exe",
  "work_path": "C:\\Games\\Cyberpunk2077",
  "args": "",
  "use_default_desktop": false
}
```

**Пример использования** ([DrovaKeeneticDesktop_fork1](https://github.com/AALagutin/DrovaKeeneticDesktop_fork1), `drova.py`):
```python
URL_PRODUCT = "https://services.drova.io/server-manager/product/get/{product_id}"
UUID_DESKTOP = UUID("9fd0eb43-b2bb-4ce3-93b8-9df63f209098")  # стандартный продукт-рабочий стол

class ProductInfo(BaseModel):
    product_id: UUID
    game_path: PureWindowsPath
    work_path: PureWindowsPath
    args: str
    use_default_desktop: bool
    title: str

async def get_product_info(product_id: UUID, auth_token: str) -> ProductInfo:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            URL_PRODUCT.format(product_id=product_id),
            headers={"X-Auth-Token": auth_token}
        ) as resp:
            return ProductInfo(**await resp.json())

# Проверить, использует ли игра стандартный рабочий стол:
product = await get_product_info(session.product_id, auth_token)
if product.use_default_desktop or product.product_id == UUID_DESKTOP:
    # включить стандартный рабочий стол Windows
    pass
```

---

## 12. GET /product-manager/product/listfull2

Публичный каталог всех продуктов (игр) платформы Drova. Аутентификация не требуется (но принимается).

**Заголовки:** нет (опционально `X-Auth-Token`)

**Query-параметры (опциональны):**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `limit` | integer | Максимальное число продуктов в ответе; по умолчанию возвращает все (~1.4 MB). Пример: `?limit=100` |
| `user_id` | string (UUID) | UUID мерчанта; передаётся рядом с `X-Auth-Token` в некоторых клиентах |

**Пример ответа** (поля `requiredAccount` и `inShopUrl` раскрыты благодаря [DTWO-Steam-to-Drova-games-sync](https://github.com/AALagutin/DTWO-Steam-to-Drova-games-sync)):
```json
[
  {
    "productId": "ffffffff-0000-1111-2222-333333333333",
    "title": "Cyberpunk 2077",
    "requiredAccount": "Steam",
    "inShopUrl": "https://store.steampowered.com/app/1091500/"
  },
  {
    "productId": "d5f88d94-87d5-11e7-bb31-000000003778",
    "title": "Fortnite",
    "requiredAccount": "Epic",
    "inShopUrl": null
  }
]
```

**Поля ответа:**

| Поле | Тип | Описание |
|------|-----|----------|
| `productId` | string (UUID) | Идентификатор продукта в Drova |
| `title` | string | Название игры |
| `requiredAccount` | string \| null | Необходимая платформа (`"Steam"`, `"Epic"`, `null` и т.д.) |
| `inShopUrl` | string \| null | URL игры в магазине (Steam: `https://store.steampowered.com/app/{steamId}/`) |

> Steam App ID извлекается из `inShopUrl` парсингом: `inShopUrl.split("/app/")[1].split("/")[0]`.
> Для игр без `inShopUrl` используют ручной словарь соответствий (см. технику [Steam→Drova matching](#steam-локальные-данные-и-сопоставление-с-drova-catalogом)).

### Примеры использования

**[drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1)** (`api.py`):
```python
def get_products_full():
    return _get("/product-manager/product/listfull2")

games, status = get_products_full()
product_map = {game["productId"]: game["title"] for game in games}
```

**[drova-dash](https://github.com/AALagutin/drova-dash)** (`streamlit_app.py`):
```python
PRODUCTS_URL = "https://services.drova.io/product-manager/product/listfull2"

@st.cache_data(show_spinner=False, ttl=600)
def fetch_product_titles():
    r = requests.get(PRODUCTS_URL, timeout=15)
    r.raise_for_status()
    return {item["productId"]: item["title"] for item in r.json()}
```

**[Drova-Session-INFO_Fork1](https://github.com/AALagutin/Drova-Session-INFO_Fork1)** (`main.go`) — Go:
```go
resp, err := http.Get("https://services.drova.io/product-manager/product/listfull2")
// ...
type Product struct {
    ProductID string
    Title     string
}
```

**[drova-vm-watch_fork1 userscript](https://github.com/AALagutin/drova-vm-watch_fork1)** (`simpletable.js`) — JS-перехват:
```javascript
const PRODUCTS_RE = /\/product-manager\/product\/listfull2(?:\?|$)/i;

// При перехвате ответа дашборда:
if (PRODUCTS_RE.test(url)) {
    const data = await response.json();
    // data: массив объектов { productId, title, useDefaultDesktop, ... }
    for (const p of (Array.isArray(data) ? data : data.list ?? [])) {
        const id = p.productId ?? p.id ?? p.uuid;
        productTitles[id] = p.title;
    }
}
```

**[DTWO-Steam-to-Drova-games-sync](https://github.com/AALagutin/DTWO-Steam-to-Drova-games-sync)** (`drovaData.py`) — используется для сопоставления установленных Steam-игр с каталогом Drova:
```python
# Загрузка полного каталога с кешем 120 минут:
fullGamesList = tryLoadGetData(
    "fullList.json",
    "https://services.drova.io/product-manager/product/listfull2",
    cacheMinutes=120,
    setIds=True   # парсит steamId из поля inShopUrl
)

# Извлечение Steam ID из inShopUrl:
def fullListSetSteamIds(games):
    for game in games:
        if game["requiredAccount"] == "Steam" and game["inShopUrl"] \
                and "steampowered.com/app/" in game["inShopUrl"]:
            game["steamId"] = game["inShopUrl"].split("/app/")[1].split("/")[0]
    return games

# Скип дубля (Cyberpunk без DLC):
SKIP_PRODUCT_ID = "c9af5926-118e-4c8b-87d4-204099ceb6fb"
```

---

## 13. GET /accounting/statistics/most_popular_games

Публичная статистика — самые популярные игры на платформе Drova. Аутентификация не требуется.

**Заголовки:** нет

**Параметры:** нет

**Ответ:** ~3.7 KB (тела ответов в HAR-дампе отсутствуют; предположительно список игр с числом сессий).

**Источник:** наблюдается в HAR-дампах `Drova_har_v2.txt` и `drova_har_reg_file.txt` (запросы из веб-дашборда `drova.io/merchant`).

---

## 14. GET /accounting/statistics/myserverusageprepared

Статистика использования станций текущего мерчанта. Возвращает объёмные данные (77 KB).

**Заголовки:**
```
X-Auth-Token: <token>
```

**Query-параметры:** неизвестны (не зафиксированы в HAR).

**Ответ:** ~77 KB (тела ответов в HAR-дампе отсутствуют; вероятно, временные ряды по сессиям/выручке).

**Источник:** HAR-дамп `Drova_har_v2.txt`.

---

## 15. GET /accounting/unpayedstats/{user_id}

Неоплаченный остаток / незакрытые начисления для указанного пользователя.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Path-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `user_id` | string (UUID) | UUID мерчанта/пользователя |

**Ответ:** ~27 байт (возможно число или `{"amount": 0}`; точная схема неизвестна — тело ответа отсутствует в HAR).

**Источник:** HAR-дамп `Drova_har_v2.txt`.

---

## 16. GET /geo/byprefix

Автодополнение географических локаций по вводимому тексту. Аутентификация не требуется. Используется в UI при выборе/настройке региона станции.

**Заголовки:** нет

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `prefix` | string | Начало названия города/региона для поиска |

**Пример запроса:**
```
GET https://services.drova.io/geo/byprefix?prefix=Моск
```

**Ответ:** ~114 байт (предположительно массив строк или объектов `{name, id}`; точная схема неизвестна — тело ответа отсутствует в HAR).

**Источник:** HAR-дамп `Drova_har_v2.txt`.

---

## 17. GET /server-manager/serverproduct/list4edit2/{server_id}/{product_id}

Получить конфигурацию конкретной игры на конкретной станции (вариант эндпоинта 7 с двумя path-параметрами).

**Заголовки:**
```
X-Auth-Token: <token>
```

**Path-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `server_id` | string (UUID) | UUID станции |
| `product_id` | string (UUID) | UUID игры/продукта |

**Ответ:** содержит конфигурацию одной записи (аналогично элементу массива из эндпоинта 7 — поля `productId`, `enabled`, `verified`, `game_path`, `work_path`, `allowed_paths`, `args` и т.д.; точная схема неизвестна — тело ответа отсутствует в HAR).

**Источник:** HAR-дамп `Drova_har_v2.txt`.

---

## 18. POST /server-manager/serverproduct/add/{server_id}/{product_id}

Добавить игру (продукт) к станции — создать запись `serverproduct`.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Path-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `server_id` | string (UUID) | UUID станции |
| `product_id` | string (UUID) | UUID игры для добавления |

**Query-параметры (опциональны):**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `user_id` | string (UUID) | UUID мерчанта |

**Тело запроса:** пустое (параметры передаются в path и query).

**Пример** ([DTWO-Steam-to-Drova-games-sync](https://github.com/AALagutin/DTWO-Steam-to-Drova-games-sync), `drovaData.py`):
```python
url = f"https://services.drova.io/server-manager/serverproduct/add/{dvServerID}/{productId}"
response = requests.post(
    url,
    params={"user_id": dvUserID},
    headers={"X-Auth-Token": dvAuthToken},
    timeout=2
)
```

**Ответ:** HTTP 200 (тело ответа отсутствует в HAR; предположительно созданный объект `serverproduct`).

**Источник:** HAR-дамп `Drova_har_v2.txt`; [DTWO-Steam-to-Drova-games-sync](https://github.com/AALagutin/DTWO-Steam-to-Drova-games-sync).

---

## 19. POST /server-manager/serverproduct/set_enabled/{server_id}/{product_id}/{value}

Включить или отключить доступность игры на станции (без снятия с публикации). Самый часто вызываемый эндпоинт в HAR — 562 запроса.

**Заголовки:**
```
X-Auth-Token: <token>
```

**Path-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `server_id` | string (UUID) | UUID станции |
| `product_id` | string (UUID) | UUID игры |
| `value` | boolean (`true`/`false`) | `true` — включить, `false` — отключить |

**Тело запроса:** пустое.

**Пример:**
```
POST https://services.drova.io/server-manager/serverproduct/set_enabled/00df3618-de85-44ab-90fd-dba52ac12440/39251d85-c1d8-4df7-9d2e-15f686039f04/true
```

**Ответ:** HTTP 200 (тело ответа отсутствует в HAR).

> Отличие от эндпоинта 6 (`/servers/{id}/set_published/{value}`): эндпоинт 6 управляет **публичностью всей станции**, эндпоинт 19 управляет **доступностью конкретной игры на станции**.

**Источник:** HAR-дамп `Drova_har_v2.txt` (562 запроса — наиболее используемый эндпоинт в сессии).

---

## 20. POST /server-manager/serverproduct/update

Обновить конфигурацию игры на станции: пути, аргументы запуска, статус верификации.

**Заголовки:**
```
X-Auth-Token: <token>
Content-Type: application/json
```

**Тело запроса (JSON):**

| Поле | Тип | Описание |
|------|-----|----------|
| `server_id` | string (UUID) | UUID станции |
| `product_id` | string (UUID) | UUID игры |
| `verified` | string | Статус верификации: `"READY"`, `"NOT_READY"` и т.д. |
| `enabled` | boolean | Включена ли игра на станции |
| `game_path` | string \| null | Путь к исполняемому файлу игры |
| `work_path` | string \| null | Рабочая директория (или `null`) |
| `allowed_paths` | array \| null | Дополнительные разрешённые пути (или `null`) |
| `args` | string \| null | Аргументы командной строки (или `null`) |

**Пример тела:**
```json
{
  "server_id": "00df3618-de85-44ab-90fd-dba52ac12440",
  "product_id": "39251d85-c1d8-4df7-9d2e-15f686039f04",
  "verified": "READY",
  "enabled": false,
  "game_path": "C:\\Program Files (x86)\\Steam\\Steam.exe",
  "work_path": null,
  "allowed_paths": null,
  "args": null
}
```

**Ответ:** HTTP 200 (тело ответа отсутствует в HAR; вероятно, обновлённый объект `serverproduct`).

**Источник:** HAR-дампы `Drova_har_v2.txt` и `drova_har_reg_file.txt`.

---

## Модели данных

### SessionsEntity

```python
class SessionsEntity(BaseModel):
    uuid: UUID
    product_id: UUID
    client_id: UUID
    created_on: datetime
    finished_on: datetime | None = None
    status: StatusEnum       # NEW | HANDSHAKE | ACTIVE | ABORTED | FINISHED
    creator_ip: IPv4Address
    abort_comment: str | None = None
    score: int | None = None
    score_reason: int | None = None
    score_text: str | None = None
    billing_type: str | None = None
```

### ProductInfo

```python
class ProductInfo(BaseModel):
    product_id: UUID
    game_path: PureWindowsPath
    work_path: PureWindowsPath
    args: str
    use_default_desktop: bool
    title: str
```

---

## Источники

| Репозиторий | Язык | Основные эндпоинты |
|-------------|------|-------------------|
| [DrovaKeeneticDesktop_fork1](https://github.com/AALagutin/DrovaKeeneticDesktop_fork1) | Python (aiohttp + asyncssh) | `/session-manager/sessions` (state=NEW/HANDSHAKE), `/server-manager/product/get/{id}`; TCP-прокси порт 7985; SSH-управление Windows (Shadow Defender, патчи реестра, очистка лаунчеров) |
| [drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1) | Python (requests) | `/accounting/myaccount`, `/session-manager/sessions`, `/server-manager/servers`, `/server-manager/serverproduct/list4edit2/{id}`, `/server-manager/serverendpoint/list/{id}`, `/product-manager/product/listfull2` |
| [drova-dash](https://github.com/AALagutin/drova-dash) | Python (requests + Streamlit) | `/server-manager/servers/public/web`, `/product-manager/product/listfull2` |
| [drova-vm-watch_fork1](https://github.com/AALagutin/drova-vm-watch_fork1) | Python (requests) + JS (userscripts) | `/token-verifier/renewProxyToken`, `/session-manager/sessions`, `/server-manager/servers/{id}`, `/server-manager/servers/{id}/set_published/{value}`, `/server-manager/servers/server_names`, `/product-manager/product/listfull2` |
| [Drova-Session-INFO_Fork1](https://github.com/AALagutin/Drova-Session-INFO_Fork1) | Go (net/http) | `/server-manager/servers`, `/session-manager/sessions`, `/product-manager/product/listfull2` |
| [steambulkvalidate_fork1](https://github.com/AALagutin/steambulkvalidate_fork1) | Python | — (локальная утилита Steam, Drova API не использует) |
| [DROVA_NOTIFIER_Fork1](https://github.com/AALagutin/DROVA_NOTIFIER_Fork1) | Go (net/http) | — (Drova API не использует; сессии определяет по процессу `ese.exe` и TCP-порту 7990; внешний вызов только `ipinfo.io`) |
| [DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1) | Go (net/http) | `/session-manager/sessions`, `/product-manager/product/listfull2`; + `ipinfo.io`, `LibreHardwareMonitor`, `GeoLite2/GitHub`, `Telegram Bot API` |
| HAR-дампы `Drova_har_v2.txt` / `drova_har_reg_file.txt` | Browser HAR (Chrome DevTools) | 659 запросов к `services.drova.io`; дали **8 новых эндпоинтов** (#13–#20); тела ответов в дампе отсутствуют |
| [DTWO-Steam-to-Drova-games-sync](https://github.com/AALagutin/DTWO-Steam-to-Drova-games-sync) | Python (requests + vdf + pywin32) | `/product-manager/product/listfull2`, `/server-manager/serverproduct/list4edit2/{id}`, `/server-manager/serverproduct/add/{id}/{id}`; раскрыты поля `requiredAccount`, `inShopUrl`; техника Steam ACF-парсинга |

---

## Сопутствующие техники и внешние API

### Пассивный захват IP игрока через TCP (порт 7990)

Используется в [DROVA_NOTIFIER_Fork1](https://github.com/AALagutin/DROVA_NOTIFIER_Fork1) вместо опроса Drova API. Нотификатор пассивно слушает TCP-порты, на которые Drova-клиент (`ese.exe`) устанавливает соединение, и извлекает IP из метаданных входящего подключения.

**Порты:**

| Константа | Порт | Назначение |
|-----------|------|------------|
| `remoutPort` | `7990` | Порт, на который Drova-клиент игрока подключается к станции; даёт **внешний IP игрока** |
| `localPort` | `139` | SMB/NetBIOS; входящее соединение показывает, какой локальный интерфейс использует станция; даёт **локальный IP сервера** |

**Глобальные переменные, заполняемые при подключении:**
```go
var (
    remoteAddr string  // внешний IP игрока
    localAddr  string  // локальный IP сервера
)
```

**Запуск слушателей** (`main.go`):
```go
const (
    remoutPort = "7990"
    localPort  = "139"
)

go listenPort(remoutPort) // горутина: ждёт подключения клиента игрока
go listenPort(localPort)  // горутина: ждёт любого SMB-соединения
```

**Приём соединения и извлечение IP** (`main.go`):
```go
func listenPort(port string) {
    listener, err := net.Listen("tcp", ":"+port)
    if err != nil {
        log.Println("Ошибка при прослушивании порта: ", err)
        return
    }
    defer listener.Close()
    for {
        conn, err := listener.Accept()
        if err != nil {
            return
        }
        go findIP(conn)
    }
}

func findIP(conn net.Conn) {
    // IP игрока — из RemoteAddr входящего соединения
    remoteIP := conn.RemoteAddr().String()        // "1.2.3.4:54321"
    ip, _, _ := net.SplitHostPort(remoteIP)
    remoteAddr = ip                               // -> "1.2.3.4"

    // IP сервера — из LocalAddr того же соединения
    localIP := conn.LocalAddr().String()
    locip, _, _ := net.SplitHostPort(localIP)
    localAddr = locip

    conn.Close()
}
```

**Использование в основном цикле** (`main.go`):
```go
// После детектирования запуска ese.exe и определения игры:
gamerIP := remoteAddr                  // IP, захваченный через порт 7990
serverIP := localAddr                  // локальный IP сервера
city, region, isp := ipInfo(remoteAddr) // геолокация через ipinfo.io

chatMessage := hostname + " - " + gamerIP +
    "\nНачало сессии - " + startTimeApp +
    "\nИгра - " + game +
    "\nserverIP = " + serverIP +
    "\nГород: " + city + "\nОбласть: " + region + "\nПровайдер: " + isp
```

> **Почему порт 7990:** это порт, на который Drova-клиент (`ese.exe`) подключается к станции при старте стримингового сеанса. Нотификатор не обращается к Drova API за информацией о сессии — вместо этого факт подключения к порту 7990 и является сигналом о начале сессии.

---

### ipinfo.io — геолокация IP

Используется в [DROVA_NOTIFIER_Fork1](https://github.com/AALagutin/DROVA_NOTIFIER_Fork1) для определения города, региона и провайдера подключающегося игрока. IP для запроса получается методом выше (TCP порт 7990).

**Метод:** `GET`
**URL:** `https://ipinfo.io/{ip}/json`
**Auth:** нет
**Параметры:** IP-адрес клиента в пути URL

**Пример ответа:**
```json
{
  "ip": "1.2.3.4",
  "city": "Moscow",
  "region": "Moscow",
  "org": "AS12345 Example ISP"
}
```

**Пример использования** (`main.go`):
```go
type IPInfoResponse struct {
    IP     string `json:"ip"`
    City   string `json:"city"`
    Region string `json:"region"`
    ISP    string `json:"org"`
}

func ipInfo(ip string) (city, region, isp string) {
    apiURL := fmt.Sprintf("https://ipinfo.io/%s/json", ip)
    resp, err := http.Get(apiURL)
    if err != nil {
        log.Fatal(err)
    }
    defer resp.Body.Close()
    var info IPInfoResponse
    json.NewDecoder(resp.Body).Decode(&info)
    return info.City, info.Region, info.ISP
}
```

Вызывается после того, как нотификатор принял входящее TCP-соединение на порт `7990` и получил IP игрока.

В [DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1) вызывается с тем же `ipinfo.io`, но IP берётся из поля `creator_ip` ответа `/session-manager/sessions`, а не из TCP.

---

### Определение локального IP через сетевые интерфейсы

Используется в [DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1) (`main.go`) как альтернатива прослушиванию порта 139. Выбирает интерфейс с наибольшим исходящим трафиком за 15 секунд.

**Функция определения активного интерфейса** (`ipinf.go`):
```go
func getSpeed() (name string, maxSpeed float64) {
    r1, _ := net.IOCounters(true)   // снимок счётчиков байт по интерфейсам
    time.Sleep(15 * time.Second)
    r2, _ := net.IOCounters(true)   // второй снимок через 15 с
    for i, r := range r2 {
        outgoing := float64(r.BytesSent - r1[i].BytesSent)
        if outgoing > maxSpeed {
            maxSpeed = outgoing
            name = r.Name           // имя интерфейса с максимальным исходящим
        }
    }
    return
}
```

**Получение IP выбранного интерфейса** (`main.go`):
```go
func getInterface() (localAddr, nameInterface string) {
    maxInterfaceName, _ := getSpeed()
    interfaces, _ := net.Interfaces()
    for _, iface := range interfaces {
        addrs, _ := iface.Addrs()
        var localIP string
        for _, addr := range addrs {
            if ip, ok := addr.(*net.IPNet); ok {
                localIP = ip.String() // "192.168.1.100/24"
            }
        }
        if iface.Name == maxInterfaceName {
            localAddr = localIP
        }
    }
    return
}
```

> V1 (DROVA_NOTIFIER) получал локальный IP через `LocalAddr()` входящего TCP-соединения на порт 139. V2 (DrovaNotifierV2) использует `net.IOCounters()` для выбора самого нагруженного интерфейса — что надёжнее на машинах с несколькими сетевыми адаптерами.

---

### LibreHardwareMonitor — локальный HTTP API температур

Используется в [DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1) (`gettemp.go`) для мониторинга температуры CPU/GPU и оборотов вентиляторов. Требует запущенного [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) с включённым веб-сервером.

**Метод:** `GET`
**URL:** `http://localhost:8085/data.json`
**Auth:** нет (локальный)
**Параметры:** нет

**Структура ответа** — рекурсивное дерево узлов:
```go
type Node struct {
    ID       int    `json:"id"`
    Text     string `json:"Text"`     // название узла ("CPU Package", "GPU Core" и т.д.)
    Min      string `json:"Min"`      // мин. значение ("35,0 °C")
    Value    string `json:"Value"`    // текущее значение ("67,0 °C")
    Max      string `json:"Max"`      // макс. значение
    ImageURL string `json:"ImageURL"` // иконка категории
    Children []Node `json:"Children"` // дочерние узлы
}
```

**Пример использования** (`gettemp.go`):
```go
func GetTemperature() (tCPU, tGPU, tGPUhs, fan1, fanp1, fan2, fanp2 float64, tMessage string) {
    // Проверка доступности:
    if _, err := http.Get("http://localhost:8085/data.json"); err != nil {
        return // LHM не запущен
    }
    resp, err := http.Get("http://localhost:8085/data.json")
    if err != nil {
        return
    }
    defer resp.Body.Close()
    body, _ := io.ReadAll(resp.Body)

    var root Node
    json.Unmarshal(body, &root)
    // Обход дерева для поиска нужных датчиков...
}
```

Значения порогов (CPU/GPU max temp, обороты вентилятора) конфигурируются в `config.txt`:
```
CPUtmax = 85
GPUtmax = 85
GPUhsTmax = 90
FANt = 75
FANrpm = 900
```

---

### Автообновление базы GeoLite2 через GitHub API

Используется в [DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1) (`ipinf.go`) и [Drova-Session-INFO_Fork1](https://github.com/AALagutin/Drova-Session-INFO_Fork1) (`main.go`). Сравнивает дату последнего релиза с датой локального файла, при необходимости скачивает новые базы.

**Шаг 1 — получить дату последнего релиза:**

| Поле | Значение |
|------|----------|
| Метод | GET |
| URL | `https://api.github.com/repos/P3TERX/GeoLite.mmdb/releases/latest` |
| Auth | нет |

```go
type Release struct {
    PublishedAt time.Time `json:"published_at"`
}

resp, _ := http.Get("https://api.github.com/repos/P3TERX/GeoLite.mmdb/releases/latest")
var release Release
json.NewDecoder(resp.Body).Decode(&release)
// release.PublishedAt сравнивается с os.Stat(mmdbFile).ModTime()
```

**Шаг 2 — скачать файлы баз (если релиз новее):**

| Файл | URL |
|------|-----|
| ASN база | `https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb` |
| City база | `https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb` |

```go
func downloadFile(filepath, url string) error {
    resp, err := http.Get(url)
    if err != nil {
        return err
    }
    defer resp.Body.Close()
    out, _ := os.Create(filepath)
    defer out.Close()
    io.Copy(out, resp.Body)
    return nil
}
```

После скачивания базы используются офлайн через `github.com/oschwald/maxminddb-golang` для определения города, региона и ASN/провайдера по IP — без сетевых запросов.

---

### Telegram Bot API

Используется в [DrovaNotifierV2_Fork1](https://github.com/AALagutin/DrovaNotifierV2_Fork1) (`telegram.go`) для отправки уведомлений о сессиях и приёма команд. Токен и chat_id хранятся в `config.txt`.

**Конфигурация** (`config.txt`):
```
Tokenbot = 123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ChatID = -100123456789
ServiceChatID = -100987654321
UserID = 123456789
CommandON = true
```

#### POST /bot{token}/sendMessage

```go
// Через библиотеку go-telegram-bot-api/v5:
func SendMessage(botToken string, chatID int64, text string, mesID int) (int, error) {
    bot, _ := tgbotapi.NewBotAPI(botToken)
    msg := tgbotapi.NewMessage(chatID, text)
    msg.ParseMode = "HTML"
    if mesID != 0 {
        msg.ReplyToMessageID = mesID // ответ на конкретное сообщение
    }
    sent, err := bot.Send(msg)
    return sent.MessageID, err
    // Retry: до 3 попыток с паузой 1 сек
}
```

**Параметры тела:**

| Поле | Тип | Описание |
|------|-----|----------|
| `chat_id` | int64 | ID чата или канала |
| `text` | string | HTML-текст сообщения |
| `parse_mode` | string | `"HTML"` |
| `reply_to_message_id` | int | Опционально: ID сообщения для ответа |

**Ответ:** возвращает `MessageID` отправленного сообщения (используется для последующего удаления).

#### POST /bot{token}/deleteMessage

Прямой HTTP-запрос (без библиотеки):

```go
func delMessage(chatID, messageID string) {
    url := fmt.Sprintf("https://api.telegram.org/bot%s/deleteMessage", BotToken)
    body, _ := json.Marshal(map[string]string{
        "chat_id":    chatID,
        "message_id": messageID,
    })
    http.Post(url, "application/json", bytes.NewBuffer(body))
}
```

#### GET /bot{token}/getUpdates (long polling)

```go
// Через библиотеку: таймаут 60 сек
u := tgbotapi.NewUpdate(0)
u.Timeout = 60
updates := bot.GetUpdatesChan(u)
// Внутри библиотека вызывает:
// GET https://api.telegram.org/bot<TOKEN>/getUpdates?timeout=60&offset=<N>

for update := range updates {
    if update.Message != nil {
        switch update.Message.Command() {
        case "start":   // ...
        case "stop":    // ...
        }
    }
}
```

---

### TCP-прокси к Windows-серверу Drova (порт 7985)

Используется в [DrovaKeeneticDesktop_fork1](https://github.com/AALagutin/DrovaKeeneticDesktop_fork1) (`drova_socket.py`, `drova_server_binary.py`). Linux-хост (Keenetic/роутер) принимает входящие TCP-соединения от клиента Drova и прозрачно проксирует их на Windows-игровую машину.

**Порты:**

| Направление | Адрес | Порт | Источник |
|-------------|-------|------|---------|
| Входящий (от клиента Drova) | `0.0.0.0` | `$DROVA_SOCKET_LISTEN` | env var |
| Исходящий (к Windows-серверу) | `$WINDOWS_HOST` | `7985` | hardcoded |

**Протокол бинарного подтверждения:**

Windows-сервер Drova при готовности посылает байт `\x01`. DrovaSocket ждёт его перед тем, как выполнять SSH-логику подготовки станции:

```python
# drova_server_binary.py
BLOCK_SIZE = 4096

async def server_need_reply(reader, writer, is_answered: Future):
    while True:
        readed_bytes = await reader.read(BLOCK_SIZE)
        if b"\x01" in readed_bytes and not found_answer:
            found_answer = True
            is_answered.set_result(True)   # сервер подтвердил готовность
        writer.write(readed_bytes)
        await writer.drain()
```

**Запуск сервера** (`drova_socket.py`):
```python
# Слушаем на 0.0.0.0:DROVA_SOCKET_LISTEN, лимит 1 соединение
self.server = await asyncio.start_server(
    self.server_accept, "0.0.0.0", self.drova_socket_listen, limit=1
)

async def server_accept(self, reader, writer):
    # Открываем исходящее соединение к Windows:
    target_socket = await asyncio.open_connection(self.windows_host, 7985)
    drova_pass = DrovaBinaryProtocol(Socket(reader, writer), Socket(*target_socket))
    if await drova_pass.wait_server_answered():
        await self._run_server_acked()  # SSH → BeforeConnect → Wait → AfterDisconnect
```

> Аналог V1 (DROVA_NOTIFIER, порт 7990) — там порт использовался пассивно для захвата IP игрока. Здесь (DrovaKeeneticDesktop) — активный TCP-прокси для ретрансляции игрового трафика.

---

### Архитектура DrovaKeeneticDesktop_fork1 — два режима работы

#### Режим poll (drova_poll)

Периодически опрашивает Drova API. Подходит когда TCP-прокси не нужен.

```
loop:
  SSH → Windows
  ├── CheckDesktop()      # GET /session-manager/sessions → /server-manager/product/get/{id}
  │   └── is_desktop_session?
  ├── [нет] WaitNewDesktopSession()   # poll раз в 1 сек
  └── [да]  BeforeConnect()           # Shadow Defender + патчи
             WaitFinishOrAbort()      # poll раз в 1 сек
             AfterDisconnect()        # выход из Shadow Defender + reboot
  sleep(1)
```

#### Режим socket (drova_socket)

Срабатывает при входящем TCP-соединении на `DROVA_SOCKET_LISTEN`:

```
client → TCP:DROVA_SOCKET_LISTEN
  │
  ├── open_connection(WINDOWS_HOST, 7985)
  ├── proxy traffic (binary passthrough, 4096 bytes/chunk)
  ├── wait \x01 from Windows server
  └── if answered:
        SSH → Windows
        CheckDesktop() → BeforeConnect() → WaitFinishOrAbort() → AfterDisconnect()
```

#### Проверка «десктопной сессии»

UUID продукта `9fd0eb43-b2bb-4ce3-93b8-9df63f209098` зарезервирован за стандартным рабочим столом Windows. Если `product_id` сессии совпадает с ним — сессия десктопная без дополнительного API-запроса. Иначе делается запрос к `/server-manager/product/get/{product_id}` и проверяется поле `use_default_desktop`.

```python
UUID_DESKTOP = UUID("9fd0eb43-b2bb-4ce3-93b8-9df63f209098")

async def check_desktop_session(self, session: SessionsEntity) -> bool:
    if session.product_id == UUID_DESKTOP:
        return True
    product_info = await get_product_info(session.product_id, auth_token=...)
    return product_info.use_default_desktop
```

---

### SSH-управление Windows-станцией

DrovaKeeneticDesktop_fork1 управляет Windows-машиной через SSH (библиотека `asyncssh`). Кодировка — `windows-1251` для совместимости с локалью Windows.

**Конфигурация подключения** (из `.env`):

| Переменная | Пример | Описание |
|-----------|--------|----------|
| `WINDOWS_HOST` | `192.168.0.10` | IP Windows-машины |
| `WINDOWS_LOGIN` | `Administrator` | Логин SSH |
| `WINDOWS_PASSWORD` | `VeryStrongPassword` | Пароль SSH |
| `DROVA_SOCKET_LISTEN` | `7985` | Порт TCP-сервера на Linux |
| `SHADOW_DEFENDER_PASSWORD` | `ReallyVeryStrongPassword` | Пароль Shadow Defender CLI |
| `SHADOW_DEFENDER_DRIVES` | `CDE` | Буквы дисков для защиты снапшотом |

**Получение токена Drova из реестра** (`commands.py`):
```python
# Команда запускается на Windows через SSH:
# reg query HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers /s /f auth_token

r_auth_token = re.compile(r"auth_token\s+REG_SZ\s+(?P<auth_token>\S+)", re.MULTILINE)
r_servers    = re.compile(r"servers\\(?P<server_id>\S+)", re.MULTILINE)
```

Токен кешируется в `ExpiringDict` с TTL 60 секунд.

---

### Shadow Defender — снапшот-защита Windows

[Shadow Defender](https://www.shadow-defender.com/) создаёт снапшот файловой системы. Все изменения за сессию (файлы, реестр) откатываются при выходе из режима.

**CLI-обёртка** (`commands.py`, `ShadowDefenderCLI`):

```
C:\Program Files\Shadow Defender\CmdTool.exe /pwd:"<пароль>" /enter:CDE /now
C:\Program Files\Shadow Defender\CmdTool.exe /pwd:"<пароль>" /exit:CDE /reboot /now
```

| Действие | Команда | Момент вызова |
|----------|---------|---------------|
| Включить снапшот | `/enter:<диски>` | `BeforeConnect` (до начала сессии) |
| Выключить и откатить | `/exit:<диски>` | `AfterDisconnect` (после сессии) |
| Перезагрузить | `/reboot` | `AfterDisconnect` (после выхода из снапшота) |
| Применить изменения | `/commit:<диск>` | — (не используется в основном флоу) |
| Показать статус | `/list` | `drova_validate` (проверка пароля) |

---

### Патчи Windows-окружения перед сессией

Применяются в `BeforeConnect` (`patch.py`) через `reg add` по SSH. Цель — изолировать игрока от системных инструментов.

**Ограничения реестра (`PatchWindowsSettings`):**

| Ключ реестра | Параметр | Значение | Эффект |
|-------------|---------|---------|--------|
| `HKCU\...\Windows\System` | `DisableCMD` | `2` | Запрет CMD |
| `HKCU\...\Policies\System` | `DisableTaskMgr` | `1` | Запрет Task Manager |
| `HKCU\...\Windows Script Host` | `Enabled` | `0` | Запрет VBScript |
| `HKCU\...\Policies\Explorer` | `NoClose` | `1` | Запрет выключения |
| `HKLM\...\Policies\System` | `HideFastUserSwitching` | `1` | Скрыть смену пользователя |

**Блокировка исполняемых файлов** (через реестр `DisallowRun`):
```
regedit.exe, powershell.exe, powershell_ise.exe, mmc.exe, gpedit.msc
perfmon.exe, anydesk.exe, rustdesk.exe
ProcessHacker.exe, procexp.exe, procexp64.exe, autoruns.exe
soundpad.exe, SoundpadService.exe
```

После применения патчей: `gpupdate /target:user /force` + перезапуск `explorer.exe`.

---

### Удаление токенов игровых лаунчеров перед сессией

Применяется в `BeforeConnect` (`patch.py`). Удаляет сохранённые данные авторизации, чтобы предыдущий игрок не оставил доступ к своим аккаунтам.

| Патч | Лаунчер | Действие |
|------|---------|---------|
| `EpicGamesAuthDiscard` | Epic Games | Очистка `GameUserSettings.ini` |
| `SteamAuthDiscard` | Steam | Очистка `loginusers.vdf` |
| `UbisoftAuthDiscard` | Ubisoft Connect | Удаление `ConnectSecureStorage.dat` и `user.dat` |
| `WargamingAuthDiscard` | Wargaming | Удаление `user_info.xml` |

Все файлы изменяются через SFTP (`asyncssh.start_sftp_client()`). Перед патчингом соответствующие процессы лаунчеров завершаются через `taskkill`.

---

### Steam локальные данные и сопоставление с Drova-каталогом

Используется в [DTWO-Steam-to-Drova-games-sync](https://github.com/AALagutin/DTWO-Steam-to-Drova-games-sync) (`localData.py`, `drovaData.py`). Никаких HTTP-запросов к Steam API нет — все данные читаются с диска.

#### Шаг 1: Путь к Steam из реестра

```python
# Windows Registry:
key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
steamFolder = winreg.QueryValueEx(key, "InstallPath")[0]
# → например: "C:\Program Files (x86)\Steam"
```

#### Шаг 2: Все библиотеки Steam из VDF

```python
import vdf

with open(os.path.join(steamFolder, "steamapps", "libraryfolders.vdf"), "r") as f:
    steamLibraries = vdf.load(f)

# libraryfolders.vdf содержит пути ко всем папкам Steam-библиотек:
for key in steamLibraries["libraryfolders"].keys():
    library = os.path.join(steamLibraries["libraryfolders"][key]["path"], "steamapps")
    steamFolders.append(library)
```

#### Шаг 3: Список установленных игр из ACF-файлов

```python
# Каждая установленная игра имеет файл appmanifest_<id>.acf в папке steamapps:
for filename in os.listdir(folder):
    if filename.endswith(".acf"):
        with open(os.path.join(folder, filename), "r") as f:
            acf_data = vdf.load(f)
            app_id  = acf_data["AppState"]["appid"]         # Steam App ID
            name    = acf_data["AppState"]["name"]           # Название игры
            size_gb = round(float(acf_data["AppState"]["SizeOnDisk"]) / 1073741824, 1)
            auto_update = int(acf_data["AppState"]["AutoUpdateBehavior"])
```

**Поля ACF:**

| Поле | Описание |
|------|----------|
| `appid` | Steam App ID (используется для сопоставления с Drova) |
| `name` | Отображаемое имя игры |
| `SizeOnDisk` | Размер в байтах (делим на 1 073 741 824 → GB) |
| `AutoUpdateBehavior` | 0=авто, 1=только при запуске, 2=не обновлять |

#### Шаг 4: Сопоставление Steam → Drova productId

```python
# В ответе /product-manager/product/listfull2 есть поле inShopUrl:
# "https://store.steampowered.com/app/1091500/"
# Из него извлекается Steam ID:
for game in drovaFullGamesList:
    if game["requiredAccount"] == "Steam" and game["inShopUrl"] \
            and "steampowered.com/app/" in game["inShopUrl"]:
        game["steamId"] = game["inShopUrl"].split("/app/")[1].split("/")[0]

# Сопоставление: localGame["appid"] == drovaGame["steamId"]
```

**Ручной словарь для игр без `inShopUrl`:**
```python
manualIds = [
    {"productId": "b6346f52-f780-42a9-98a2-1c7d6c4b4473", "title": "PlanetSide 2",              "steamId": "218230"},
    {"productId": "7d628e11-0bb1-442c-98a4-8106176b13b8", "title": "The Walking Dead: Season Two","steamId": "261030"},
]
```

#### Шаг 5: Игры не из Steam (hardcoded paths)

Для игр Epic/HoYo/Wargaming/Battlestate проверяется существование exe-файла:
```python
localList = {
    "Fortnite":        {"productId": "d5f88d94-87d5-11e7-bb31-000000003778",
                        "exePaths": [r"C:\Program Files\Epic Games\Fortnite\...\FortniteClient-Win64-Shipping.exe"]},
    "Genshin Impact":  {"productId": "b05acb00-93ab-4b6d-ab6c-792f72e43665",
                        "exePaths": [r"C:\Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact.exe"]},
    "Escape from Tarkov": {"productId": "cdb6d8f4-6b6f-4f92-a240-56447ed9b42d",
                        "exePaths": [r"c:\Battlestate Games\EFT\EscapeFromTarkov.exe"]},
    # ... и другие
}
# Wargaming/Lesta — парсинг game_info.xml для версии
```

**Известные Drova product UUID для non-Steam игр:**

| Игра | productId |
|------|-----------|
| Fortnite | `d5f88d94-87d5-11e7-bb31-000000003778` |
| Honkai: Star Rail | `5e3c271e-da2a-4898-a420-9b49d74f2695` |
| Genshin Impact | `b05acb00-93ab-4b6d-ab6c-792f72e43665` |
| Zenless Zone Zero | `0864eddb-d20d-437d-a322-329ccda51ad0` |
| Wuthering Waves | `934386db-5b9e-4635-ab70-59d02b6a988d` |
| Escape from Tarkov | `cdb6d8f4-6b6f-4f92-a240-56447ed9b42d` |
| Escape from Tarkov Arena | `1b4253f2-11ae-4d14-92aa-b506a18cf247` |
| Мир кораблей (RU) | `21d8c648-8d39-4b3f-8989-69d58fbe7dff` |
| World of Warships (EU) | `21d8c648-8d39-4b3f-8989-69d58fbe7e00` |
| Мир танков (RU) | `d5f88d94-87d5-11e7-bb31-000000002432` |
| World of Tanks (EU) | `c1661a7c-4950-4346-a193-103fb385b6d6` |
| Cyberpunk 2077 (без DLC, дубль — **пропускать**) | `c9af5926-118e-4c8b-87d4-204099ceb6fb` |

#### Кеш-стратегия (файловый JSON-кеш)

| Данные | Файл | TTL |
|--------|------|-----|
| Локальный список игр | `localGamesList.json` | 5 мин |
| Список игр станции | `{server_id}.json` | 10 мин |
| Полный каталог Drova | `fullList.json` | 120 мин |

При сетевой ошибке — fallback на устаревший кеш без TTL.
