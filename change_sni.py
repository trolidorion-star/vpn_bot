"""
СКРИПТ ДЛЯ СМЕНЫ SNI НА РОССИЙСКИЙ ДОМЕН
"""

import json

# Путь к конфигу
config_path = "/usr/local/x-ui/bin/config.json"

# Новый SNI (российский домен из белого списка)
NEW_SNI = "gosuslugi.ru"

print("=" * 80)
print("🔧 СМЕНА SNI В КОНФИГЕ XRAY")
print("=" * 80)
print(f"📍 Новый SNI: {NEW_SNI}")
print()

# 1. Резервная копия
print("1️⃣  Создание резервной копии...")
import subprocess
subprocess.run(["cp", config_path, config_path + ".backup_sni"])
print("   ✅ Резервная копия создана")
print()

# 2. Читаем конфиг
print("2️⃣  Чтение конфига...")
with open(config_path, 'r') as f:
    config = json.load(f)
print("   ✅ Конфиг прочитан")
print()

# 3. Ищем и меняем SNI
print("3️⃣  Поиск и замена SNI...")
changed = False

# Ищем во всех inbounds
if "inbounds" in config:
    for inbound in config["inbounds"]:
        if "streamSettings" in inbound:
            stream = inbound["streamSettings"]
            if isinstance(stream, str):
                stream = json.loads(stream)
            
            # Проверяем realitySettings
            if "realitySettings" in stream:
                reality = stream["realitySettings"]
                
                # Меняем serverNames (массив)
                if "serverNames" in reality:
                    old_sni = reality["serverNames"]
                    reality["serverNames"] = [NEW_SNI]
                    print(f"   ✅ serverNames изменен: {old_sni} → [{NEW_SNI}]")
                    changed = True
                
                # Меняем serverName во внутреннем settings
                if "settings" in reality:
                    settings = reality["settings"]
                    if "serverName" in settings:
                        old_server_name = settings["serverName"]
                        settings["serverName"] = NEW_SNI
                        print(f"   ✅ settings.serverName изменен: {old_server_name} → {NEW_SNI}")
                        changed = True
                
                # Меняем target (если microsoft.com)
                if "target" in reality:
                    old_target = reality["target"]
                    if "microsoft.com" in old_target:
                        new_target = old_target.replace("microsoft.com:443", "gosuslugi.ru:443")
                        reality["target"] = new_target
                        print(f"   ✅ target изменен: {old_target} → {new_target}")
                        changed = True
                
                # Сохраняем streamSettings
                inbound["streamSettings"] = json.dumps(stream)

if not changed:
    print("   ⚠️  SNI не найден в конфиге")
else:
    print()
    print("4️⃣  Сохранение конфига...")
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print("   ✅ Конфиг сохранен")
    print()

# 5. Перезапуск
print("5️⃣  Перезапуск Xray...")
subprocess.run(["x-ui", "restart"])
print()

print("=" * 80)
print("✅ СМЕНА SNI ЗАВЕРШЕНА")
print("=" * 80)
print()
print("💡 ДАЛЬНЕЙШИЕ ДЕЙСТВИЯ:")
print("   1. Обновите клиентский конфиг (новый QR/ссылка из x-ui)")
print("   2. Попробуйте подключиться")
print("   3. Смотрите логи: /root/watch_logs.sh")
print()
