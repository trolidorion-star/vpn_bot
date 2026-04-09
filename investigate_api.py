"""
Скрипт-исследователь API панели x-ui.
Проверяет все возможные endpoints для работы с инбаундами.
НЕ ВНОСИТ ИЗМЕНЕНИЙ - только безопасные GET запросы.
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

BASE_URL = f"http://{HOST}:{PORT}/{WEB_BASE_PATH}"
INBOUND_ID = 1  # Инбаунд 443

# ========================================
# СПИСОК ENDPOINTS ДЛЯ ПРОВЕРКИ
# ========================================
ENDPOINTS_TO_CHECK = [
    # Основные операции с инбаундами
    {
        "name": "GET inbound by ID",
        "method": "GET",
        "path": f"/panel/api/inbounds/{INBOUND_ID}",
        "description": "Получить конкретный инбаунд по ID"
    },
    {
        "name": "GET update endpoint",
        "method": "GET", 
        "path": f"/panel/api/inbounds/update/{INBOUND_ID}",
        "description": "Проверка endpoint обновления"
    },
    {
        "name": "GET add endpoint",
        "method": "GET",
        "path": "/panel/api/inbounds/add",
        "description": "Проверка endpoint добавления"
    },
    {
        "name": "GET delete endpoint",
        "method": "GET",
        "path": f"/panel/api/inbounds/del/{INBOUND_ID}",
        "description": "Проверка endpoint удаления"
    },
    {
        "name": "GET onlines",
        "method": "GET",
        "path": "/panel/api/inbounds/onlines",
        "description": "Список онлайн клиентов"
    },
    
    # Альтернативные пути (могут быть в других версиях)
    {
        "name": "GET inbound (alt path 1)",
        "method": "GET",
        "path": "/panel/api/inbounds/get/{INBOUND_ID}",
        "description": "Альтернативный путь получения инбаунда"
    },
    {
        "name": "GET update (alt path 1)",
        "method": "GET",
        "path": f"/panel/api/inbounds/updateInbound/{INBOUND_ID}",
        "description": "Альтернативный путь обновления"
    },
    {
        "name": "GET update (alt path 2)",
        "method": "GET",
        "path": f"/panel/api/inbounds/updateInbound",
        "description": "Альтернативный путь обновления (без ID)"
    },
    
    # POST endpoints (попробуем с пустым телом)
    {
        "name": "POST update (empty)",
        "method": "POST",
        "path": f"/panel/api/inbounds/update/{INBOUND_ID}",
        "data": {},
        "description": "Проверка POST на endpoint обновления"
    },
    {
        "name": "POST add (empty)",
        "method": "POST", 
        "path": "/panel/api/inbounds/add",
        "data": {},
        "description": "Проверка POST на endpoint добавления"
    },
]

# ========================================
# БЕЗОПАСНАЯ ПРОВЕРКА ENDPOINT
# ========================================
async def check_endpoint(session, endpoint):
    """Безопасно проверяет один endpoint."""
    url = f"{BASE_URL}{endpoint['path']}"
    method = endpoint['method']
    data = endpoint.get('data')
    
    print(f"   Проверка: {method} {url}")
    
    try:
        if method == "GET":
            async with session.get(url) as resp:
                text = await resp.text()
                status = resp.status
        else:  # POST
            async with session.post(url, json=data) as resp:
                text = await resp.text()
                status = resp.status
        
        # Анализ результата
        result = {
            "name": endpoint['name'],
            "url": url,
            "method": method,
            "status": status,
            "success": False,
            "message": ""
        }
        
        if status == 200:
            # Пытаемся распарсить JSON
            try:
                json_resp = json.loads(text)
                if json_resp.get("success"):
                    result["success"] = True
                    result["message"] = f"✅ Работает! Ответ: {json_resp.get('msg', 'OK')}"
                else:
                    result["message"] = f"⚠️  Вернул success=False: {json_resp.get('msg', 'no message')}"
            except:
                # Не JSON
                result["message"] = f"⚠️  Статус 200, но не JSON: {text[:50]}..."
        
        elif status == 404:
            result["message"] = "❌ Endpoint не существует (404)"
        
        elif status == 405:
            result["message"] = f"⚠️  Метод не поддерживается (405). Возможно нужен другой метод"
        
        elif status == 401:
            result["message"] = "❌ Не авторизован (401). Проблема с сессией"
        
        elif status == 400:
            try:
                json_resp = json.loads(text)
                result["message"] = f"⚠️  Неверный запрос (400): {json_resp.get('msg', 'no message')}"
            except:
                result["message"] = f"⚠️  Неверный запрос (400): {text[:100]}"
        
        else:
            result["message"] = f"⚠️  Неожиданный статус: {status} - {text[:50]}"
        
        return result
        
    except aiohttp.ClientError as e:
        return {
            "name": endpoint['name'],
            "url": url,
            "method": method,
            "status": 0,
            "success": False,
            "message": f"❌ Ошибка подключения: {e}"
        }
    except Exception as e:
        return {
            "name": endpoint['name'],
            "url": url,
            "method": method,
            "status": 0,
            "success": False,
            "message": f"❌ Неожиданная ошибка: {e}"
        }

# ========================================
# ГЛАВНАЯ ФУНКЦИЯ
# ========================================
async def investigate():
    print("=" * 80)
    print("🔍 ИССЛЕДОВАНИЕ API ПАНЕЛИ X-UI")
    print("=" * 80)
    print(f"📍 Панель: {BASE_URL}")
    print(f"👤 Логин: {USER}")
    print(f"🎯 Inbound ID: {INBOUND_ID}")
    print()
    print("⚠️  ВНИМАНИЕ: Скрипт использует только безопасные запросы (GET + POST с пустыми данными)")
    print("   НИКАКИХ ИЗМЕНЕНИЙ НЕ БУДЕТ ВНЕСЕНО!")
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
                return
            
            login_res = await resp.json()
            if not login_res.get("success"):
                print(f"❌ Ошибка входа: {login_res.get('msg')}")
                return
            
            print("✅ Успешная авторизация")
        print()
        
        # 2. Проверяем все endpoints
        print("2️⃣  Проверка доступных endpoints...")
        print("-" * 80)
        
        results = []
        for i, endpoint in enumerate(ENDPOINTS_TO_CHECK, 1):
            print(f"\n[{i}/{len(ENDPOINTS_TO_CHECK)}] {endpoint['description']}")
            result = await check_endpoint(session, endpoint)
            results.append(result)
            print(f"   Результат: {result['message']}")
        
        print()
        print("-" * 80)
        
        # 3. Итоги
        print("\n3️⃣  ИТОГИ ИССЛЕДОВАНИЯ:")
        print("=" * 80)
        
        working = [r for r in results if r["success"]]
        not_found = [r for r in results if r["status"] == 404]
        other_status = [r for r in results if not r["success"] and r["status"] != 404]
        
        if working:
            print(f"\n✅ РАБОТАЮЩИЕ ENDPOINTS ({len(working)}):")
            for r in working:
                print(f"   • {r['name']}: {r['message']}")
        
        if not_found:
            print(f"\n❌ НЕ СУЩЕСТВУЮТ (404) - {len(not_found)} шт:")
            for r in not_found:
                print(f"   • {r['name']}")
        
        if other_status:
            print(f"\n⚠️  ДРУГИЕ СТАТУСЫ - {len(other_status)} шт:")
            for r in other_status:
                print(f"   • {r['name']}: {r['message']}")
        
        # 4. Рекомендации
        print("\n4️⃣  РЕКОМЕНДАЦИИ:")
        print("=" * 80)
        
        has_update_endpoint = any(r["success"] and "update" in r["url"].lower() for r in results)
        has_add_endpoint = any(r["success"] and "add" in r["url"].lower() for r in results)
        has_delete_endpoint = any(r["success"] and "del" in r["url"].lower() for r in results)
        
        if has_update_endpoint:
            print("✅ Есть работающий endpoint обновления - можем попробовать исправить serverName!")
        elif has_add_endpoint and has_delete_endpoint:
            print("✅ Есть endpoints добавления и удаления - можем пересоздать инбаунд!")
        else:
            print("⚠️  Обычные endpoints для работы с инбаундами не работают")
            print("   Возможно:")
            print("   - Версия панели использует другой API")
            print("   - Нужны специальные заголовки или параметры")
            print("   - Эти endpoints отключены в настройках")
        
        print()
        print("=" * 80)
        print("✅ ИССЛЕДОВАНИЕ ЗАВЕРШЕНО")
        print("=" * 80)

# ========================================
# ЗАПУСК
# ========================================
if __name__ == "__main__":
    try:
        asyncio.run(investigate())
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
