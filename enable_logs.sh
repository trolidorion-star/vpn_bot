#!/bin/bash
"""
СКРИПТ ДЛЯ ВКЛЮЧЕНИЯ ЛОГОВ XRAY
"""

echo "================================================================================"
echo "🔧 ВКЛЮЧЕНИЕ ЛОГИРОВАНИЯ XRAY"
echo "================================================================================"
echo

# 1. Резервная копия конфига
echo "1️⃣  Создание резервной копии..."
cp /usr/local/x-ui/bin/config.json /usr/local/x-ui/bin/config.json.backup
echo "   ✅ Резервная копия создана: config.json.backup"
echo

# 2. Включаем логирование
echo "2️⃣  Включение логирования..."
python3 << 'PYTHON_SCRIPT'
import json

config_path = "/usr/local/x-ui/bin/config.json"

# Читаем конфиг
with open(config_path, 'r') as f:
    config = json.load(f)

# Включаем логирование
config["log"]["access"] = "/usr/local/x-ui/access.log"
config["log"]["error"] = "/usr/local/x-ui/error.log"
config["log"]["loglevel"] = "debug"

# Сохраняем
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print("   ✅ Логирование включено")
print("      Access log: /usr/local/x-ui/access.log")
print("      Error log: /usr/local/x-ui/error.log")
print("      Level: debug")
PYTHON_SCRIPT
echo

# 3. Проверяем версию Xray
echo "3️⃣  Проверка версии Xray..."
/usr/local/x-ui/bin/xray-linux-amd64 version
echo

# 4. Перезапускаем Xray
echo "4️⃣  Перезапуск Xray..."
x-ui start
sleep 2
echo

# 5. Проверяем, что запустился
echo "5️⃣  Проверка процесса..."
ps aux | grep xray | grep -v grep

if [ $? -eq 0 ]; then
    echo "   ✅ Xray запущен"
else
    echo "   ❌ Xray НЕ запущен!"
    echo "   Проверяем логи:"
    cat /usr/local/x-ui/error.log
fi
echo

# 6. Создаем скрипт для просмотра логов
cat > /root/watch_logs.sh << 'WATCH_SCRIPT'
#!/bin/bash
echo "================================================================================"
echo "👀 СЛЕЖЕНИЕ ЗА ЛОГАМИ XRAY"
echo "================================================================================"
echo
echo "💡 Попробуйте подключиться с клиента..."
echo "   Нажмите Ctrl+C для выхода"
echo
echo "================================================================================"
tail -f /usr/local/x-ui/error.log /usr/local/x-ui/access.log
WATCH_SCRIPT

chmod +x /root/watch_logs.sh

echo "================================================================================"
echo "✅ ЛОГИРОВАНИЕ ВКЛЮЧЕНО"
echo "================================================================================"
echo
echo "💡 ДАЛЬНЕЙШИЕ ДЕЙСТВИЯ:"
echo
echo "   1. Попробуйте подключиться с клиента (v2rayNG)"
echo "   2. В СЛЕДУЮЩЕМ ТЕРМИНАЛЕ запустите:"
echo "      /root/watch_logs.sh"
echo
echo "   3. Вы увидите попытки подключения и ошибки рукопожатия"
echo
echo "   4. После попытки подключения скидывайте логи сюда"
echo
