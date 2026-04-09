"""
СОЗДАНИЕ VLESS+TLS НА ПОРТУ 443
"""

import json
import subprocess
import uuid

config_path = "/usr/local/x-ui/bin/config.json"

# Данные клиента
CLIENT_EMAIL = "user_kikiki190_27309_tls"
CLIENT_UUID = "829eb6e6-3e8b-4850-a930-157d475a1ed4"
CLIENT_FLOW = ""  # VLESS+TLS не требует Flow
CLIENT_TOTAL_GB = 1096290402304
CLIENT_EXPIRY_TIME = 1806959701952

print("=" * 80)
print("🔧 СОЗДАНИЕ VLESS+TLS НА ПОРТУ 443")
print("=" * 80)
print()

# 1. Читаем конфиг
print("1️⃣  Чтение конфига...")
with open(config_path, 'r') as f:
    config = json.load(f)
print("   ✅ Конфиг прочитан")
print()

# 2. Резервная копия
print("2️⃣  Резервная копия...")
subprocess.run(["cp", config_path, config_path + ".backup_vless_tls"])
print("   ✅ Резервная копия создана")
print()

# 3. Проверяем, занят ли 443
print("3️⃣  Проверка порта 443...")
if "inbounds" in config:
    for inbound in config["inbounds"]:
        if inbound.get("port") == 443:
            print(f"   ⚠️  Порт 443 занят: {inbound.get('protocol')} ({inbound.get('remark')})")
            print("   ❌ Нужно освободить порт 443")
            print()
            print("💡 РЕШЕНИЕ:")
            print("   Вариант 1: Удалить старый инбаунд через x-ui панель")
            print("   Вариант 2: Изменить порт старого инбаунда на другой")
            exit(1)
print("   ✅ Порт 443 свободен")
print()

# 4. Создаем VLESS+TLS инбаунд
print("4️⃣  Создание VLESS+TLS инбаунда...")
vless_tls_inbound = {
    "port": 443,
    "protocol": "vless",
    "settings": json.dumps({
        "clients": [{
            "id": CLIENT_UUID,
            "email": CLIENT_EMAIL,
            "flow": CLIENT_FLOW,
            "totalGB": CLIENT_TOTAL_GB,
            "expiryTime": CLIENT_EXPIRY_TIME,
            "enable": True,
            "limitIp": 1
        }],
        "decryption": "none"
    }),
    "streamSettings": json.dumps({
        "network": "tcp",
        "security": "tls",
        "tlsSettings": {
            "certificates": [{
                "certificateFile": "/etc/x-ui/server.crt",
                "keyFile": "/etc/x-ui/server.key"
            }],
            "serverName": "www.microsoft.com"
        }
    }),
    "sniffing": json.dumps({
        "enabled": True,
        "destOverride": ["http", "tls", "quic", "fakedns"]
    }),
    "enable": True,
    "remark": "Bobr1k_VLESS_TLS"
}

if "inbounds" not in config:
    config["inbounds"] = []

config["inbounds"].append(vless_tls_inbound)
print("   ✅ Инбаунд создан")
print()

# 5. Сохраняем конфиг
print("5️⃣  Сохранение конфига...")
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
print("   ✅ Конфиг сохранен")
print()

# 6. Перезапуск Xray
print("6️⃣  Перезапуск Xray...")
subprocess.run(["x-ui", "restart"])
print("   ✅ Xray перезапущен")
print()

# 7. Проверяем
print("7️⃣  Проверка...")
result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
if ":443" in result.stdout:
    print("   ✅ Порт 443 слушается")
else:
    print("   ❌ Порт 443 НЕ слушается!")
print()

print("=" * 80)
print("✅ VLESS+TLS ИНБАУНД СОЗДАН")
print("=" * 80)
print()
print("💡 НАСТРОЙКИ КЛИЕНТА:")
print()
print(f"   IP: 103.27.158.33")
print(f"   Порт: 443")
print(f"   UUID: {CLIENT_UUID}")
print(f"   Протокол: VLESS")
print(f"   Сеть: TCP")
print(f"   Безопасность: TLS")
print(f"   SNI: www.microsoft.com")
print(f"   Flow: (пустой)")
print()
