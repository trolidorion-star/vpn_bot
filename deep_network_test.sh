#!/bin/bash
"""
ГЛУБОКАЯ ДИАГНОСТИКА ДОСТУПНОСТИ IP ИЗ РОССИИ
"""

echo "================================================================================"
echo "🔍 ГЛУБОКАЯ ДИАГНОСТИКА ДОСТУПНОСТИ IP 103.27.158.33"
echo "================================================================================"
echo

# 1. Проверка маршрутизации
echo "1️⃣  Проверка маршрутизации:"
echo "   Таблица маршрутизации:"
ip route show
echo

echo "   Шлюз по умолчанию:"
ip route | grep default
echo

echo "   Интерфейс:"
ip addr show | grep -A 2 "ens3"
echo

# 2. Проверка DNS резолвинга
echo "2️⃣  Проверка DNS резолвинга:"
for domain in "google.com" "yandex.ru" "vk.com" "gosuslugi.ru"; do
    echo "   Пингуем $domain:"
    ping -c 2 $domain 2>&1 | grep "packets transmitted"
done
echo

# 3. Проверка traceroute
echo "3️⃣  Проверка traceroute до Russian IP:"
for target in "8.8.8.8" "77.88.8.8" "93.158.134.3"; do
    echo "   Traceroute до $target:"
    traceroute -m 10 -n $target 2>&1 | head -15
    echo
done

# 4. Проверка IPTABLES - не блокирует ли сервер исходящий трафик
echo "4️⃣  Проверка исходящих правил iptables:"
echo "   OUTPUT chain:"
iptables -L OUTPUT -n -v | head -20
echo

# 5. Проверка, может ли сервер сам себя пинговать по публичному IP
echo "5️⃣  Тест доступа к самому себе по публичному IP:"
ping -c 3 103.27.158.33
echo

# 6. Проверка, может ли сервер соединиться с русскими IP
echo "6️⃣  Тест соединения с Russian IP:"
for port in 80 443; do
    echo "   Пытаемся соединиться с 213.180.204.56 (yandex.ru):$port"
    timeout 3 bash -c "echo >/dev/tcp/213.180.204.56/$port" 2>&1
    if [ $? -eq 0 ]; then
        echo "   ✅ Соединение успешно"
    else
        echo "   ❌ Соединение НЕ удалось"
    fi
done
echo

# 7. Проверка через curl к Russian IP
echo "7️⃣  Тест HTTP запроса к Russian IP:"
for url in "http://yandex.ru" "http://vk.com" "http://gosuslugi.ru"; do
    echo "   GET $url"
    timeout 5 curl -I -s $url 2>&1 | head -5
    echo "   ---"
done
echo

# 8. Проверка открытых портов снаружи (через онлайн сервисы)
echo "8️⃣  ОНЛАЙН ПРОВЕРКА ДОСТУПНОСТИ ПОРТОВ ИЗ РОССИИ:"
echo
echo "   💡 Выполните эти команды на своем компьютере в России:"
echo
echo "   --- ПИНГ ---"
echo "   ping 103.27.158.33"
echo
echo "   --- TRACEROUTE ---"
echo "   traceroute 103.27.158.33"
echo
echo "   --- ПРОВЕРКА ПОРТОВ ---"
echo "   PowerShell (Windows):"
echo "   Test-NetConnection -ComputerName 103.27.158.33 -Port 443"
echo "   Test-NetConnection -ComputerName 103.27.158.33 -Port 8443"
echo "   Test-NetConnection -ComputerName 103.27.158.33 -Port 2053"
echo
echo "   Bash (Linux/Mac):"
echo "   nc -zv 103.27.158.33 443"
echo "   nc -zv 103.27.158.33 8443"
echo "   nc -zv 103.27.158.33 2053"
echo
echo "   --- ОНЛАЙН СЕРВИСЫ ---"
echo "   https://ping-admin.ru/index.php?lang=en&node=103.27.158.33"
echo "   https://www.whatsmyip.org/port-scanner/?ip=103.27.158.33&ports=443,8443,2053"
echo

# 9. Проверка логов Xray на предмет подключений
echo "9️⃣  Проверка, были ли вообще попытки подключения:"
if [ -f /usr/local/x-ui/access.log ]; then
    echo "   Последние 50 строк access.log:"
    tail -50 /usr/local/x-ui/access.log
elif [ -f /usr/local/x-ui/error.log ]; then
    echo "   Последние 50 строк error.log:"
    tail -50 /usr/local/x-ui/error.log
else
    echo "   ℹ️  Логи не найдены"
fi
echo

# 10. Проверка процесса Xray - не висит ли он
echo "🔟 Проверка процесса Xray:"
ps aux | grep xray | grep -v grep
echo

echo "================================================================================"
echo "✅ ДИАГНОСТИКА ЗАВЕРШЕНА"
echo "================================================================================"
echo
echo "💡 ЧТО ДЕЛАТЬ ДАЛЬШЕ:"
echo
echo "   1. ВЫПОЛНИТЕ команды из раздела 8 на компьютере В РОССИИ"
echo "   2. Скиньте результаты сюда"
echo
echo "   ЭТО ПОКАЖЕТ НАМ:"
echo "   - Доходят ли пинги до сервера"
echo "   - Где обрывается трассировка"
echo "   - Открыты ли порты снаружи"
echo "   - Есть ли соединения из России"
echo
