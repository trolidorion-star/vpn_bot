"""
СКРИПТ ДЛЯ СОЗДАНИЯ SHADOWSOCKS-2022 ИНБАУНДА
"""

import json
import subprocess
import uuid

# Путь к конфигу
config_path = "/usr/local/x-ui/bin/config.json"

# Настройки нового инбаунда
NEW_PORT = 8443  # Нестандартный порт
NEW_PROTOCOL = "shadowsocks"
NEW_METHOD = "2022-blake3-aes-128-gcm"  # Современный метод
NEW_SNI = ""  # Shadowsocks не требует SNI

# Данные клиента
CLIENT_EMAIL = "user_kikiki190_27309_shadowsocks"
CLIENT_TOTAL_GB = 1096290402304  # ~1 TB
CLIENT_EXPIRY_TIME = 1806959701952

# Генерация пароля для Shadowsocks 2022
import base64
import os
CLIENT_PASSWORD = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').rstrip('=')

print("=" * 80)
print("🔧 СОЗДАНИЕ SHADOWSOCKS-2022 ИНБАУНДА")
print("=" * 80)
print(f"📍 Порт: {NEW_PORT}")
print(f"📍 Протокол: {NEW_PROTOCOL}")
print(f"📍 Метод: {NEW_METHOD}")
print(f"📍 Клиент: {CLIENT_EMAIL}")
print()

# 1. Читаем текущий конфиг
print("1️⃣  Чтение текущего конфига...")
with open(config_path, 'r') as f:
    config = json.load(f)

print("   ✅ Конфиг прочитан")

# 2. Резервная копия
print("2️⃣  Создание резервной копии...")
subprocess.run(["cp", config_path, config_path + ".backup_shadowsocks"])
print("   ✅ Резервная копия создана")
print()

# 3. Создаем новый инбаунд Shadowsocks
print("3️⃣  Создание нового инбаунда...")
shadowsocks_inbound = {
    "port": NEW_PORT,
    "protocol": NEW_PROTOCOL,
    "settings": json.dumps({
        "method": NEW_METHOD,
        "clients": [{
            "email": CLIENT_EMAIL,
            "password": CLIENT_PASSWORD,
            "totalGB": CLIENT_TOTAL_GB,
            "expiryTime": CLIENT_EXPIRY_TIME,
            "enable": True,
            "limitIp": 1
        }],
        "network": "tcp,udp"
    }),
    "streamSettings": json.dumps({
        "network": "tcp",
        "security": "none"
    }),
    "sniffing": json.dumps({
        "enabled": True,
        "destOverride": ["http", "tls", "quic", "fakedns"]
    }),
    "enable": True,
    "remark": "Bobr1k_Shadowsocks"
}

print(f"   Пароль клиента: {CLIENT_PASSWORD}")
print()

# 4. Добавляем в конфиг
if "inbounds" not in config:
    config["inbounds"] = []

config["inbounds"].append(shadowsocks_inbound)

print("4️⃣  Сохранение конфига...")
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print("   ✅ Конфиг сохранен")
print()

# 5. Перезапуск Xray
print("5️⃣  Перезапуск Xray...")
subprocess.run(["x-ui", "restart"])
print("   ✅ Xray перезапущен")
print()

# 6. Проверяем, что порт слушается
print("6️⃣  Проверка порта...")
result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
if f":{NEW_PORT}" in result.stdout:
    print(f"   ✅ Порт {NEW_PORT} слушается")
else:
    print(f"   ❌ Порт {NEW_PORT} НЕ слушается!")
    print(result.stdout)
print()

print("=" * 80)
print("✅ SHADOWSOCKS-2022 ИНБАУНД СОЗДАН")
print("=" * 80)
print()
print("💡 НАСТРОЙКИ КЛИЕНТА:")
print()
print(f"   IP: 103.27.158.33")
print(f"   Порт: {NEW_PORT}")
print(f"   Пароль: {CLIENT_PASSWORD}")
print(f"   Метод: {NEW_METHOD}")
print(f"   Протокол: ss://")
print()
print("💡 ДЛЯ v2rayNG:")
print(f"   1. Добавь новый профиль: + → Shadowsocks")
print(f"   2. IP: 103.27.158.33")
print(f"   3. Порт: {NEW_PORT}")
print(f"   4. Пароль: {CLIENT_PASSWORD}")
print(f"   5. Метод: {NEW_METHOD}")
print()
print("💡 ДЛЯ ТЕСТА:")
print(f"   Команда для теста:")
print(f"   ss://{CLIENT_PASSWORD}@103.27.158.33:{NEW_PORT}")
print()
