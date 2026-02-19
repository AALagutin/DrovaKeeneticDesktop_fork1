# Drova API — Карта методов

**Base URL:** `https://services.drova.io`

**Аутентификация:** все защищённые эндпоинты принимают заголовок:
```
X-Auth-Token: <token>
```
Токен получают из QR-кода в личном кабинете Drova, из Windows-реестра (`HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers`) или из файла `token.json`.

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
| `status` | string | Фильтр по статусу; можно передавать несколько раз |
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

Получить список продуктов (игр), настроенных на конкретной станции, с возможностью редактирования. Показывает статус включённости/публикации каждой игры.

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

Публичный каталог всех продуктов (игр) платформы Drova. Аутентификация не требуется.

**Заголовки:** нет

**Параметры:** нет

**Пример ответа:**
```json
[
  {
    "productId": "ffffffff-0000-1111-2222-333333333333",
    "title": "Cyberpunk 2077"
  }
]
```

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
| [DrovaKeeneticDesktop_fork1](https://github.com/AALagutin/DrovaKeeneticDesktop_fork1) | Python (aiohttp) | `/session-manager/sessions`, `/server-manager/product/get/{id}` |
| [drova-telegram-server-info-fork1](https://github.com/AALagutin/drova-telegram-server-info-fork1) | Python (requests) | `/accounting/myaccount`, `/session-manager/sessions`, `/server-manager/servers`, `/server-manager/serverproduct/list4edit2/{id}`, `/server-manager/serverendpoint/list/{id}`, `/product-manager/product/listfull2` |
| [drova-dash](https://github.com/AALagutin/drova-dash) | Python (requests + Streamlit) | `/server-manager/servers/public/web`, `/product-manager/product/listfull2` |
| [drova-vm-watch_fork1](https://github.com/AALagutin/drova-vm-watch_fork1) | Python (requests) + JS (userscripts) | `/token-verifier/renewProxyToken`, `/session-manager/sessions`, `/server-manager/servers/{id}`, `/server-manager/servers/{id}/set_published/{value}`, `/server-manager/servers/server_names`, `/product-manager/product/listfull2` |
| [Drova-Session-INFO_Fork1](https://github.com/AALagutin/Drova-Session-INFO_Fork1) | Go (net/http) | `/server-manager/servers`, `/session-manager/sessions`, `/product-manager/product/listfull2` |
| [steambulkvalidate_fork1](https://github.com/AALagutin/steambulkvalidate_fork1) | Python | — (локальная утилита Steam, Drova API не использует) |
| [DROVA_NOTIFIER_Fork1](https://github.com/AALagutin/DROVA_NOTIFIER_Fork1) | Go (net/http) | — (Drova API не использует; сессии определяет по процессу `ese.exe` и TCP-порту 7990; внешний вызов только `ipinfo.io`) |

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
