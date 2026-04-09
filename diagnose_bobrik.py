"""
Диагностический скрипт для проверки инбаунда 443 на панели x-ui.

Проверяет:
- Структуру инбаунда (VLESS + Reality)
- Наличие Flow в настройках клиентов
- Reality settings (publicKey, serverName, fingerprint, shortIds)
- Доступность endpoint для обновления инбаунда
"""

import asyncio
import aiohttp
import json
import sys

# ========================================
# НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К ПАНЕЛИ
# ========================================
HOST = "103.27.158.33"
PORT = "80"  # HTTP по умолчанию
WEB_BASE_PATH = "bobrik_admin"
USER = "bobrik_boss"
PASS = "wsx48kkio2"

BASE_URL = f"http://{HOST}:{PORT}/{WEB_BASE_PATH}"

# ========================================
# ДИАГНОСТИКА
# ========================================
async def diagnose():
    print("=" * 70)
    print("🔍 ДИАГНОСТИКА ПАНЕЛИ X-UI v2.8.11")
    print("=" * 70)
    print(f"📍 Адрес панели: {BASE_URL}")
    print(f"👤 Логин: {USER}")
    print()

    # Создаем сессию с такими же настройками как в твоем боте
    connector = aiohttp.TCPConnector(ssl=False)
    jar = aiohttp.CookieJar(unsafe=True)
    
    async with aiohttp.ClientSession(connector=connector, cookie_jar=jar) as session:
        # ========================================
        # 1. АВТОРИЗАЦИЯ
        # ========================================
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

        # ========================================
        # 2. ПОЛУЧЕНИЕ СПИСКА ИНБАУНДОВ
        # ========================================
        print("2️⃣  Получение списка инбаундов...")
        async with session.get(f"{BASE_URL}/panel/api/inbounds/list") as resp:
            data = await resp.json()
            if not data.get("success"):
                print(f"❌ Ошибка получения списка: {data.get('msg')}")
                return
            
            inbounds = data.get("obj", [])
            print(f"✅ Получено {len(inbounds)} инбаундов")
            
            # Показываем все инбаунды кратко
            print()
            print("📋 Список всех инбаундов:")
            for ib in inbounds:
                port = ib.get("port")
                protocol = ib.get("protocol")
                remark = ib.get("remark", "без названия")
                print(f"   - Порт {port}: {protocol} ({remark})")
        print()

        # ========================================
        # 3. ПОИСК ИНБАУНДА 443
        # ========================================
        print("3️⃣  Поиск инбаунда на порту 443...")
        target = None
        for ib in inbounds:
            if ib.get("port") == 443:
                target = ib
                break
        
        if not target:
            print("❌ Инбаунд на порту 443 НЕ НАЙДЕН!")
            print()
            print("💡 Возможные причины:")
            print("   - Порт 443 используется для другого инбаунда")
            print("   - Инбаунд был удален")
            return
        
        print(f"✅ Инбаунд найден! ID: {target['id']}")
        print(f"   Протокол: {target.get('protocol')}")
        print(f"   Заметка: {target.get('remark', 'без названия')}")
        print(f"   Статус: {'✅ включен' if target.get('enable') else '❌ выключен'}")
        print()

        # ========================================
        # 4. АНАЛИЗ SETTINGS
        # ========================================
        print("4️⃣  Анализ настроек (settings)...")
        settings_str = target.get("settings", "{}")
        try:
            settings = json.loads(settings_str)
            
            # Показываем базовую информацию
            print(f"   Структура JSON: ✅ валидный")
            print(f"   Количество клиентов: {len(settings.get('clients', []))}")
            
            # Проверяем Flow в клиентах
            clients = settings.get("clients", [])
            if clients:
                print()
                print("   📊 Клиенты:")
                for i, client in enumerate(clients, 1):
                    email = client.get("email", f"без email")
                    flow = client.get("flow", "")
                    flow_status = "✅" if flow else "❌ ОТСУТСТВУЕТ"
                    print(f"      {i}. {email}")
                    print(f"         Flow: '{flow}' {flow_status}")
                    
                    # Показываем другие важные поля
                    if "mldsa65" in client:
                        print(f"         ⚠️ mldsa65: {client.get('mldsa65')}")
                    if "seed" in client:
                        print(f"         ⚠️ seed: {client.get('seed')}")
            else:
                print("   ⚠️ Клиентов нет (пустой список)")
            
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            print(f"   Raw settings: {settings_str[:200]}")
        print()

        # ========================================
        # 5. АНАЛИЗ STREAM SETTINGS (Reality)
        # ========================================
        print("5️⃣  Анализ потока (streamSettings)...")
        stream_str = target.get("streamSettings", "{}")
        try:
            stream = json.loads(stream_str)
            network = stream.get("network", "не указан")
            security = stream.get("security", "не указан")
            
            print(f"   Сеть (network): {network}")
            print(f"   Безопасность (security): {security}")
            
            if security == "reality":
                print()
                print("   🔐 Reality Settings:")
                reality = stream.get("realitySettings", {})
                print(f"      Public Key (pbk): {reality.get('publicKey', '❌ не указан')}")
                print(f"      Server Name (SNI): {reality.get('serverName', '❌ не указан')}")
                print(f"      Fingerprint (uTLS): {reality.get('fingerprint', '❌ не указан')}")
                print(f"      Short IDs: {reality.get('shortIds', [])}")
                
                # Проверяем критические поля
                if not reality.get('publicKey'):
                    print("      ⚠️ ВНИМАНИЕ: publicKey пустой!")
                if not reality.get('serverName'):
                    print("      ⚠️ ВНИМАНИЕ: serverName пустой!")
                
            elif security == "tls":
                print()
                print("   🔐 TLS Settings:")
                tls = stream.get("tlsSettings", {})
                print(f"      Server Name: {tls.get('serverName', 'не указан')}")
                print(f"      Alpn: {tls.get('alpn', [])}")
                
            else:
                print(f"   ⚠️ Неизвестный тип безопасности: {security}")
                
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга streamSettings: {e}")
            print(f"   Raw: {stream_str[:200]}")
        print()

        # ========================================
        # 6. ПРОВЕРКА ENDPOINT UPDATE
        # ========================================
        print("6️⃣  Проверка доступности endpoint обновления инбаунда...")
        update_url = f"{BASE_URL}/panel/api/inbounds/update/{target['id']}"
        
        try:
            # Пробуем GET запрос (безопасный)
            async with session.get(update_url) as resp:
                print(f"   GET {update_url}")
                print(f"   Статус: {resp.status}")
                
                if resp.status == 200:
                    text = await resp.text()
                    try:
                        res = json.loads(text)
                        print(f"   Ответ API: {res.get('msg', 'без сообщения')}")
                        print("   ✅ Endpoint доступен")
                    except:
                        print(f"   ⚠️ Не JSON ответ: {text[:100]}")
                elif resp.status == 404:
                    print("   ❌ Endpoint не существует (404)")
                    print("   ⚠️ Скрипт gemini может НЕ РАБОТАТЬ!")
                elif resp.status == 405:
                    print("   ⚠️ Метод не поддерживается (405)")
                    print("   💡 Возможно нужен POST вместо GET")
                else:
                    text = await resp.text()
                    print(f"   ❌ Неожиданный статус: {text[:100]}")
        except aiohttp.ClientError as e:
            print(f"   ❌ Ошибка запроса: {e}")
        print()

        # ========================================
        # 7. ПОЛНАЯ СТРУКТУРА ИНБАУНДА (для анализа)
        # ========================================
        print("7️⃣  Полная структура инбаунда (JSON):")
        print("-" * 70)
        
        # Красивый вывод JSON
        target_copy = target.copy()
        # Обрезаем очень длинные поля для читаемости
        if 'streamSettings' in target_copy:
            try:
                stream = json.loads(target_copy['streamSettings'])
                if 'realitySettings' in stream and 'privateKey' in stream['realitySettings']:
                    stream['realitySettings']['privateKey'] = '[скрыто]'
                if 'tlsSettings' in stream and 'certificates' in stream['tlsSettings']:
                    stream['tlsSettings']['certificates'] = '[скрыто]'
                target_copy['streamSettings'] = json.dumps(stream)
            except:
                pass
        
        print(json.dumps(target_copy, indent=2, ensure_ascii=False))
        print("-" * 70)
        print()

        # ========================================
        # 8. РЕКОМЕНДАЦИИ
        # ========================================
        print("=" * 70)
        print("💡 РЕКОМЕНДАЦИИ:")
        print("=" * 70)
        
        # Проверяем Flow
        has_flow = any(client.get("flow") for client in settings.get("clients", []))
        
        if not has_flow:
            print("⚠️  Flow отсутствует у клиентов!")
            print("   Это объясняет ошибку в логах Xray:")
            print("   'VLESS (with no Flow, etc.) is deprecated'")
            print()
        
        # Проверяем настройки Reality
        if stream.get("security") == "reality":
            reality = stream.get("realitySettings", {})
            if not reality.get("publicKey"):
                print("⚠️  Public Key пустой - нужно сгенерировать через 'Get New Cert'")
        
        # Проверяем endpoint
        print()
        if not has_flow:
            print("✅ Нужен фикс: добавить flow='xtls-rprx-vision' для всех клиентов")
            print()
        
        # Определяем метод фикса
        if any(client.get("mldsa65") or client.get("seed") for client in settings.get("clients", [])):
            print("✅ Рекомендация: очистить поля mldsa65 и seed (клиенты не поддерживают)")
        
        print()
        print("=" * 70)
        print("✅ ДИАГНОСТИКА ЗАВЕРШЕНА")
        print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(diagnose())
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
