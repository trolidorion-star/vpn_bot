"""
Скрипт для удаления клиента knz86wyq из инбаунда 443.
"""

import asyncio
import aiohttp
import json
import sys
from urllib.parse import quote

# ========================================
# НАСТРОЙКИ
# ========================================
HOST = "103.27.158.33"
PORT = "80"
WEB_BASE_PATH = "bobrik_admin"
USER = "bobrik_boss"
PASS = "wsx48kkio2"

# Данные клиента из диагностики
INBOUND_ID = 1
CLIENT_EMAIL = "knz86wyq"
CLIENT_UUID = "2b64bf68-28a9-4259-9830-08b51e8194f5"  # Из diagnostics

BASE_URL = f"http://{HOST}:{PORT}/{WEB_BASE_PATH}"

# ========================================
# УДАЛЕНИЕ КЛИЕНТА
# ========================================
async def delete_client():
    print("=" * 70)
    print("🗑️  УДАЛЕНИЕ КЛИЕНТА ИЗ ИНБАУНДА")
    print("=" * 70)
    print(f"📍 Клиент: {CLIENT_EMAIL} (UUID: {CLIENT_UUID})")
    print(f"📍 Inbound ID: {INBOUND_ID}")
    print()

    # Создаем сессию
    connector = aiohttp.TCPConnector(ssl=False)
    jar = aiohttp.CookieJar(unsafe=True)
    
    async with aiohttp.ClientSession(connector=connector, cookie_jar=jar) as session:
        # 1. Авторизация
        print("1️⃣  Авторизация...")
        async with session.post(f"{BASE_URL}/login", json={"username": USER, "password": PASS}) as resp:
            if resp.status != 200:
                print(f"❌ Ошибка HTTP {resp.status} при логине")
                return False
            
            login_res = await resp.json()
            if not login_res.get("success"):
                print(f"❌ Ошибка входа: {login_res.get('msg')}")
                return False
            
            print("✅ Успешная авторизация")
        print()

        # 2. Удаление клиента
        print("2️⃣  Удаление клиента...")
        # Endpoint: /panel/api/inbounds/{inbound_id}/delClient/{encoded_uuid}
        encoded_uuid = quote(CLIENT_UUID, safe='')
        delete_url = f"{BASE_URL}/panel/api/inbounds/{INBOUND_ID}/delClient/{encoded_uuid}"
        
        print(f"   URL: {delete_url}")
        
        async with session.post(delete_url) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"❌ Ошибка HTTP {resp.status}: {text}")
                return False
            
            result = await resp.json()
            
            if result.get("success"):
                print("✅ Клиент успешно удален!")
                print(f"   Сообщение: {result.get('msg', 'ОК')}")
                return True
            else:
                print(f"❌ Ошибка удаления: {result.get('msg')}")
                return False

# ========================================
# ПРОВЕРКА РЕЗУЛЬТАТА
# ========================================
async def verify_deletion():
    print()
    print("3️⃣  Проверка результата...")
    
    connector = aiohttp.TCPConnector(ssl=False)
    jar = aiohttp.CookieJar(unsafe=True)
    
    async with aiohttp.ClientSession(connector=connector, cookie_jar=jar) as session:
        # Авторизация
        await session.post(f"{BASE_URL}/login", json={"username": USER, "password": PASS})
        
        # Получаем список инбаундов
        async with session.get(f"{BASE_URL}/panel/api/inbounds/list") as resp:
            data = await resp.json()
            inbounds = data.get("obj", [])
            
            # Ищем инбаунд 443
            target = None
            for ib in inbounds:
                if ib.get("port") == 443:
                    target = ib
                    break
            
            if not target:
                print("❌ Инбаунд 443 не найден!")
                return
            
            # Проверяем клиентов
            settings_str = target.get("settings", "{}")
            settings = json.loads(settings_str)
            clients = settings.get("clients", [])
            
            print(f"   Осталось клиентов: {len(clients)}")
            
            # Проверяем, что knz86wyq удален
            found = False
            for client in clients:
                if client.get("email") == CLIENT_EMAIL:
                    found = True
                    print(f"   ⚠️  Клиент {CLIENT_EMAIL} ЕЩЁ ЕСТЬ!")
                    break
            
            if not found:
                print(f"   ✅ Клиент {CLIENT_EMAIL} УДАЛЕН")
                
                # Проверяем Flow у оставшихся клиентов
                print()
                print("4️⃣  Проверка Flow у оставшихся клиентов:")
                all_have_flow = True
                for client in clients:
                    email = client.get("email")
                    flow = client.get("flow", "")
                    status = "✅" if flow else "❌"
                    print(f"   {status} {email}: flow = '{flow}'")
                    if not flow:
                        all_have_flow = False
                
                if all_have_flow:
                    print()
                    print("🎉 ОТЛИЧНО! Все клиенты имеют Flow!")
                    print("   Ошибка Xray должна исчезнуть!")
                else:
                    print()
                    print("⚠️  Остались клиенты без Flow")

# ========================================
# ГЛАВНАЯ ФУНКЦИЯ
# ========================================
async def main():
    try:
        # Удаляем клиента
        success = await delete_client()
        
        if success:
            # Проверяем результат
            await verify_deletion()
            
            print()
            print("=" * 70)
            print("✅ УДАЛЕНИЕ ЗАВЕРШЕНО")
            print("=" * 70)
            print()
            print("💡 СЛЕДУЮЩИЕ ШАГИ:")
            print("   1. Перезапустите панель: x-ui restart")
            print("   2. Проверьте логи Xray: x-ui log")
            print("   3. Ошибка 'VLESS (with no Flow)' должна исчезнуть!")
            print()
        else:
            print()
            print("❌ Ошибка при удалении")
            return 1
            
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
