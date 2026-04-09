"""
ФИНАЛЬНЫЙ СКРИПТ ДЛЯ ИСПРАВЛЕНИЯ serverName.
Обновляет инбаунд 443 через POST /panel/api/inbounds/update/1
С дополнительной диагностикой.
"""

import asyncio
import aiohttp
import json
import sys

# ========================================
# НАСТРОЙКИ
# ========================================
HOST = "103.27.158.33"
PORT = "80"
WEB_BASE_PATH = "bobrik_admin"
USER = "bobrik_boss"
PASS = "wsx48kkio2"

INBOUND_ID = 1
NEW_SERVER_NAME = "www.microsoft.com"

BASE_URL = f"http://{HOST}:{PORT}/{WEB_BASE_PATH}"

# ========================================
# ПОЛУЧЕНИЕ ТЕКУЩЕГО ИНБАУНДА
# ========================================
async def get_current_inbound(session):
    """Получает текущий инбаунд из списка."""
    async with session.get(f"{BASE_URL}/panel/api/inbounds/list") as resp:
        data = await resp.json()
        if not data.get("success"):
            raise Exception(f"Ошибка получения списка: {data.get('msg')}")
        
        inbounds = data.get("obj", [])
        
        # === ДИАГНОСТИКА: Выводим все инбаунды ===
        print(f"   Найдено инбаундов: {len(inbounds)}")
        for i, ib in enumerate(inbounds, 1):
            ib_port = ib.get("port")
            ib_port_type = type(ib_port).__name__
            ib_protocol = ib.get("protocol")
            ib_remark = ib.get("remark", "")
            
            # Проверяем совпадение порта (число и строка)
            port_matches = (ib_port == 443) or (ib_port == "443")
            status = "🎯 ЦЕЛЬ" if port_matches else "  "
            
            print(f"   {status} [{i}] Port: {ib_port} ({ib_port_type}), "
                  f"Protocol: {ib_protocol}, Remark: '{ib_remark}'")
        
        print()
        
        # Ищем инбаунд 443
        for ib in inbounds:
            ib_port = ib.get("port")
            # Проверяем и число 443, и строку "443"
            if ib_port == 443 or ib_port == "443":
                print(f"   ✅ Инбаунд 443 найден: {ib.get('remark', 'без названия')}")
                return ib
        
        print("   ❌ Инбаунд 443 НЕ НАЙДЕН")
        raise Exception("Инбаунд 443 не найден")

# ========================================
# ИСПРАВЛЕНИЕ serverName
# ========================================
async def fix_server_name():
    print("=" * 80)
    print("🔧 ИСПРАВЛЕНИЕ serverName В ИНБАУНДЕ")
    print("=" * 80)
    print(f"📍 Инбаунд ID: {INBOUND_ID}")
    print(f"📍 Новый serverName: {NEW_SERVER_NAME}")
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
        
        # 2. Получаем текущий инбаунд
        print("2️⃣  Получение текущего инбаунда...")
        inbound = await get_current_inbound(session)
        print()

        # 3. Парсим streamSettings
        print("3️⃣  Анализ текущих настроек...")
        stream_str = inbound.get("streamSettings", "{}")
        
        try:
            stream = json.loads(stream_str)
        except json.JSONDecodeError as e:
            raise Exception(f"Ошибка парсинга streamSettings: {e}")
        
        # Показываем текущее значение serverName
        reality_settings = stream.get("realitySettings", {})
        internal_settings = reality_settings.get("settings", {})
        current_server_name = internal_settings.get("serverName", "")
        
        print(f"   Текущий serverName: '{current_server_name}'")
        
        if current_server_name == NEW_SERVER_NAME:
            print(f"   ⚠️  serverName уже установлен в {NEW_SERVER_NAME}!")
            print("   Исправление не требуется.")
            return True
        print()

        # 4. Исправляем serverName
        print("4️⃣  Исправление serverName...")
        internal_settings["serverName"] = NEW_SERVER_NAME
        
        # Обновляем структуру
        reality_settings["settings"] = internal_settings
        stream["realitySettings"] = reality_settings
        
        # Собираем данные для отправки
        update_data = {
            "id": inbound["id"],
            "port": inbound["port"],
            "protocol": inbound["protocol"],
            "settings": inbound["settings"],
            "streamSettings": json.dumps(stream),
            "sniffing": inbound["sniffing"],
            "enable": inbound.get("enable", True),
            "remark": inbound.get("remark", ""),
            "listen": inbound.get("listen", ""),
            "expiryTime": inbound.get("expiryTime", 0),
            "trafficReset": inbound.get("trafficReset", "never"),
            "lastTrafficResetTime": inbound.get("lastTrafficResetTime", 0)
        }
        
        print(f"   Новый serverName: '{NEW_SERVER_NAME}'")
        print()

        # 5. Отправляем обновление
        print("5️⃣  Отправка обновления...")
        update_url = f"{BASE_URL}/panel/api/inbounds/update/{INBOUND_ID}"
        
        print(f"   URL: {update_url}")
        print(f"   Метод: POST")
        
        async with session.post(update_url, json=update_data) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Ошибка HTTP {resp.status}: {text}")
            
            result = await resp.json()
            
            if not result.get("success"):
                raise Exception(f"Ошибка обновления: {result.get('msg')}")
            
            print("✅ Обновление успешно!")
            print(f"   Сообщение: {result.get('msg', 'OK')}")
        print()

        # 6. Проверка результата
        print("6️⃣  Проверка результата...")
        updated_inbound = await get_current_inbound(session)
        updated_stream = json.loads(updated_inbound.get("streamSettings", "{}"))
        updated_reality = updated_stream.get("realitySettings", {})
        updated_settings = updated_reality.get("settings", {})
        updated_server_name = updated_settings.get("serverName", "")
        
        if updated_server_name == NEW_SERVER_NAME:
            print(f"✅ serverName успешно обновлен: '{updated_server_name}'")
            print()
            print("🎉 ПОБЕДА! serverName исправлен!")
            return True
        else:
            print(f"❌ serverName не обновлен. Текущее значение: '{updated_server_name}'")
            print("⚠️  Возможно, панель игнорирует это поле")
            return False

# ========================================
# ГЛАВНАЯ ФУНКЦИЯ
# ========================================
async def main():
    try:
        success = await fix_server_name()
        
        if success:
            print()
            print("=" * 80)
            print("✅ ИСПРАВЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО")
            print("=" * 80)
            print()
            print("💡 СЛЕДУЮЩИЕ ШАГИ:")
            print("   1. Перезапустите панель: x-ui restart")
            print("   2. Проверьте логи Xray: x-ui log")
            print("   3. Попробуйте подключиться с клиента")
            print()
            print("🚀 VPN должен заработать!")
            print()
        else:
            print()
            print("❌ serverName не обновился")
            print("⚠️  Возможно, нужно другой подход")
            return 1
            
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
