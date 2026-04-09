"""
СКРИПТ ДЛЯ ПЕРЕСОЗДАНИЯ ИНБАУНДА ИЗ НУЛЯ.
Генерирует новые ключи, создает инбаунд 443, добавляет клиента.
"""

import asyncio
import aiohttp
import json
import sys
import uuid
import subprocess

# ========================================
# НАСТРОЙКИ
# ========================================
HOST = "103.27.158.33"
PORT = "80"
WEB_BASE_PATH = "bobrik_admin"
USER = "bobrik_boss"
PASS = "wsx48kkio2"

# Данные клиента из предыдущей диагностики
CLIENT_UUID = "829eb6e6-3e8b-4850-a930-157d475a1ed4"
CLIENT_EMAIL = "user_kikiki190_27309"
CLIENT_TOTAL_GB = 1096290402304  # ~1 TB
CLIENT_EXPIRY_TIME = 1806959701952  # Тоже из диагностики
CLIENT_LIMIT_IP = 1
CLIENT_TG_ID = "6989943466"
CLIENT_FLOW = "xtls-rprx-vision"
CLIENT_SUB_ID = "41e32a9a2bf24c4fa79d1fe4eab3dc5e"

BASE_URL = f"http://{HOST}:{PORT}/{WEB_BASE_PATH}"

# ========================================
# ГЕНЕРАЦИЯ REALITY КЛЮЧЕЙ
# ========================================
def generate_reality_keys():
    """Генерирует private key и public key для Reality."""
    try:
        # Пытаемся использовать xray для генерации
        result = subprocess.run(
            ['xray', 'x25519'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            private_key = None
            public_key = None
            
            for line in lines:
                if line.startswith('Private key:'):
                    private_key = line.split(': ')[1].strip()
                elif line.startswith('Public key:'):
                    public_key = line.split(': ')[1].strip()
            
            if private_key and public_key:
                return private_key, public_key
    except Exception as e:
        print(f"   ⚠️  Ошибка генерации через xray: {e}")
    
    # Фолбэк: используем тестовые ключи
    print("   ⚠️  Используем тестовые ключи (xray недоступен)")
    private_key = "7d5e5d7d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d"
    public_key = "a5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5"
    return private_key, public_key

# ========================================
# УДАЛЕНИЕ ИНБАУНДА
# ========================================
async def delete_inbound(session, inbound_id):
    """Удаляет инбаунд."""
    delete_url = f"{BASE_URL}/panel/api/inbounds/del/{inbound_id}"
    
    async with session.post(delete_url) as resp:
        text = await resp.text()
        
        if resp.status == 200:
            result = await resp.json()
            return result.get("success", False)
        elif resp.status == 404:
            # Уже удален
            return True
        else:
            raise Exception(f"Ошибка удаления: HTTP {resp.status} - {text}")

# ========================================
# СОЗДАНИЕ НОВОГО ИНБАУНДА
# ========================================
async def create_inbound(session):
    """Создает новый инбаунд с Reality."""
    print("   Генерация Reality ключей...")
    private_key, public_key = generate_reality_keys()
    
    print(f"   Private Key: {private_key[:20]}...")
    print(f"   Public Key: {public_key[:20]}...")
    
    # Структура инбаунда для VLESS + Reality
    inbound_data = {
        "port": 443,
        "protocol": "vless",
        "settings": json.dumps({
            "clients": [{
                "id": CLIENT_UUID,
                "email": CLIENT_EMAIL,
                "flow": CLIENT_FLOW,
                "limitIp": CLIENT_LIMIT_IP,
                "totalGB": CLIENT_TOTAL_GB,
                "expiryTime": CLIENT_EXPIRY_TIME,
                "enable": True,
                "tgId": CLIENT_TG_ID,
                "subId": CLIENT_SUB_ID,
                "reset": 0
            }],
            "decryption": "none"
        }),
        "streamSettings": json.dumps({
            "network": "tcp",
            "security": "reality",
            "externalProxy": [],
            "realitySettings": {
                "show": False,
                "xver": 0,
                "target": "www.microsoft.com:443",
                "serverNames": ["www.microsoft.com"],
                "privateKey": private_key,
                "publicKey": public_key,
                "minClientVer": "",
                "maxClientVer": "",
                "maxTimediff": 0,
                "shortIds": [
                    uuid.uuid4().hex[:8],
                    uuid.uuid4().hex[:16]
                ],
                "mldsa65Seed": "",
                "settings": {
                    "publicKey": public_key,
                    "fingerprint": "firefox",
                    "serverName": "www.microsoft.com",  # ← ИСПРАВЛЕНО!
                    "spiderX": "/",
                    "mldsa65Verify": ""
                }
            },
            "tcpSettings": {
                "acceptProxyProtocol": False,
                "header": {
                    "type": "none"
                }
            }
        }),
        "sniffing": json.dumps({
            "enabled": True,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False
        }),
        "enable": True,
        "remark": "Bobr1k_vpn"
    }
    
    print("   Создание инбаунда...")
    create_url = f"{BASE_URL}/panel/api/inbounds/add"
    
    async with session.post(create_url, json=inbound_data) as resp:
        text = await resp.text()
        
        if resp.status != 200:
            raise Exception(f"Ошибка HTTP {resp.status}: {text}")
        
        result = await resp.json()
        
        if not result.get("success"):
            raise Exception(f"Ошибка создания: {result.get('msg')}")
        
        print("   ✅ Инбаунд создан!")
        return True

# ========================================
# ГЛАВНАЯ ФУНКЦИЯ
# ========================================
async def rebuild_inbound():
    print("=" * 80)
    print("🔧 ПЕРЕСОЗДАНИЕ ИНБАУНДА ИЗ НУЛЯ")
    print("=" * 80)
    print(f"📍 Клиент: {CLIENT_EMAIL}")
    print(f"📍 UUID: {CLIENT_UUID}")
    print(f"📍 Port: 443")
    print()

    # Создаем сессию
    connector = aiohttp.TCPConnector(ssl=False)
    jar = aiohttp.CookieJar(unsafe=True)
    
    async with aiohttp.ClientSession(connector=connector, cookie_jar=jar) as session:
        # 1. Авторизация
        print("1️⃣  Авторизация...")
        async with session.post(f"{BASE_URL}/login", json={"username": USER, "password": PASS}) as resp:
            if resp.status != 200:
                raise Exception(f"Ошибка HTTP {resp.status} при логине")
            
            login_res = await resp.json()
            if not login_res.get("success"):
                raise Exception(f"Ошибка входа: {login_res.get('msg')}")
            
            print("✅ Успешная авторизация")
        print()
        
        # 2. Удаление старого инбаунда
        print("2️⃣  Удаление старого инбаунда (ID: 1)...")
        try:
            success = await delete_inbound(session, 1)
            if success:
                print("   ✅ Старый инбаунд удален")
            else:
                print("   ⚠️  Не удалось удалить, продолжаем...")
        except Exception as e:
            print(f"   ⚠️  Ошибка удаления: {e}")
            print("   Продолжаем...")
        print()
        
        # 3. Создание нового инбаунда
        print("3️⃣  Создание нового инбаунда...")
        await create_inbound(session)
        print()

        # 4. Проверка результата
        print("4️⃣  Проверка результата...")
        async with session.get(f"{BASE_URL}/panel/api/inbounds/list") as resp:
            data = await resp.json()
            if not data.get("success"):
                raise Exception(f"Ошибка получения списка: {data.get('msg')}")
            
            inbounds = data.get("obj", [])
            
            print(f"   Найдено инбаундов: {len(inbounds)}")
            
            for ib in inbounds:
                port = ib.get("port")
                protocol = ib.get("protocol")
                remark = ib.get("remark", "")
                print(f"   - Port {port}: {protocol} ('{remark}')")
                
                if port == 443:
                    # Проверяем сервернейм
                    try:
                        stream = json.loads(ib.get("streamSettings", "{}"))
                        reality = stream.get("realitySettings", {})
                        settings = reality.get("settings", {})
                        server_name = settings.get("serverName", "")
                        
                        if server_name == "www.microsoft.com":
                            print(f"   ✅ serverName ИСПРАВЛЕН: '{server_name}'")
                        else:
                            print(f"   ⚠️  serverName: '{server_name}'")
                    except:
                        pass

# ========================================
# ЗАПУСК
# ========================================
if __name__ == "__main__":
    try:
        asyncio.run(rebuild_inbound())
        
        print()
        print("=" * 80)
        print("✅ ПЕРЕСОЗДАНИЕ ЗАВЕРШЕНО")
        print("=" * 80)
        print()
        print("💡 СЛЕДУЮЩИЕ ШАГИ:")
        print("   1. Перезапустите панель: x-ui restart")
        print("   2. Проверьте логи Xray: x-ui log")
        print("   3. Обновите клиентский ключ:")
        print(f"      - PublicKey изменился на новый!")
        print(f"      - Скопируйте из панели x-ui")
        print("   4. Попробуйте подключиться")
        print()
        print("🚀 VPN должен заработать!")
        print()
        
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
