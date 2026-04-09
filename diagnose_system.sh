#!/bin/bash
"""
СИСТЕМНАЯ ДИАГНОСТИКА VPN
Проверяет порты, файлрвол, соединения.
"""

echo "================================================================================"
echo "🔍 СИСТЕМНАЯ ДИАГНОСТИКА VPN"
echo "================================================================================"
echo

# 1. Проверка, слушает ли Xray порт 443
echo "1️⃣  Проверка: слушает ли Xray порт 443..."
echo "   Команда: ss -tlnp | grep :443"
ss -tlnp | grep :443

if [ $? -eq 0 ]; then
    echo "   ✅ Xray слушает порт 443"
else
    echo "   ❌ Xray НЕ слушает порт 443!"
    echo "   Проверяем все прослушиваемые порты:"
    ss -tlnp
fi
echo

# 2. Проверка процесса Xray
echo "2️⃣  Проверка процесса Xray..."
echo "   Команда: ps aux | grep xray"
ps aux | grep -v grep | grep xray

if [ $? -eq 0 ]; then
    echo "   ✅ Процесс Xray запущен"
else
    echo "   ❌ Процесс Xray НЕ запущен!"
fi
echo

# 3. Проверка файлрвола (iptables)
echo "3️⃣  Проверка правил iptables..."
echo "   Команда: iptables -L -n -v"
iptables -L -n -v | head -30

echo
echo "   Проверка, есть ли правило на 443 порт:"
iptables -L INPUT -n -v | grep -E "(443|dpt:443)"

if [ $? -eq 0 ]; then
    echo "   ✅ Есть правило для 443"
else
    echo "   ⚠️  Нет явного правила для 443 (возможно, используется ACCEPT по умолчанию)"
fi
echo

# 4. Проверка UFW
echo "4️⃣  Проверка UFW (если активен)..."
if command -v ufw &> /dev/null; then
    echo "   Команда: ufw status"
    ufw status
else
    echo "   ℹ️  UFW не установлен"
fi
echo

# 5. Проверка доступа к порту снаружи
echo "5️⃣  Проверка: можно ли подключиться к 443 порту..."
echo "   Команда: nc -zv 127.0.0.1 443"
nc -zv 127.0.0.1 443

if [ $? -eq 0 ]; then
    echo "   ✅ Порт 443 доступен локально"
else
    echo "   ❌ Порт 443 НЕ доступен локально!"
fi
echo

# 6. Проверка DNS
echo "6️⃣  Проверка DNS..."
echo "   Пингуем www.microsoft.com:"
ping -c 2 www.microsoft.com

if [ $? -eq 0 ]; then
    echo "   ✅ DNS работает"
else
    echo "   ❌ DNS не работает!"
fi
echo

# 7. Проверка маршрутизации
echo "7️⃣  Проверка маршрутизации..."
echo "   Таблица маршрутизации:"
ip route show

echo
echo "   Шлюз по умолчанию:"
ip route | grep default
echo

# 8. Проверка логов Xray на предмет ошибок
echo "8️⃣  Последние строки логов Xray (если есть)..."
if [ -f /var/log/xray/*.log ]; then
    tail -20 /var/log/xray/*.log
elif [ -f /usr/local/x-ui/x-ui.log ]; then
    tail -20 /usr/local/x-ui/x-ui.log
else
    echo "   ℹ️  Файлы логов не найдены в стандартных местах"
    echo "   Попробуем найти:"
    find / -name "*.log" 2>/dev/null | grep -i xray | head -5
fi
echo

# 9. Проверка, занят ли 443 порт другим процессом
echo "9️⃣  Проверка: не занят ли 443 другой программой..."
echo "   Все процессы на порту 443:"
lsof -i :443 2>/dev/null || echo "   lsof недоступен, используем netstat:"
netstat -tlnp 2>/dev/null | grep :443 || echo "   netstat недоступен"
echo

# 10. Попытка создать TCP соединение с Xray (тестовый)
echo "🔟 Тестовое соединение с Xray (curl)..."
echo "   Пытаемся соединиться с localhost:443..."
timeout 5 curl -v telnet://127.0.0.1:443 2>&1 | head -20

echo
echo "================================================================================"
echo "✅ ДИАГНОСТИКА ЗАВЕРШЕНА"
echo "================================================================================"
echo
echo "💡 Что проверить:"
echo "   1. Если Xray НЕ слушает 443 - перезапустите: x-ui restart"
echo "   2. Если есть DROP правила в iptables - добавьте: iptables -I INPUT -p tcp --dport 443 -j ACCEPT"
echo "   3. Если UFW активен и блокирует - разрешите: ufw allow 443/tcp"
echo "   4. Если DNS не работает - проверьте /etc/resolv.conf"
echo
