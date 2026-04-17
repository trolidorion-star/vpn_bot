# Emergency Recovery (Admin + VPN)

Если после смены портов/настроек пропал доступ к админке и VPN не работает:

```bash
cd /root/my-private
git fetch --all
git checkout feature/webapp-final
git pull --ff-only origin feature/webapp-final
chmod +x deploy/recover_stack.sh
sudo bash deploy/recover_stack.sh /root/my-private yadreno-vpn
```

Проверка после восстановления:

```bash
systemctl status yadreno-vpn --no-pager -l
ss -tulpen | egrep ':443|:8081|:8082'
journalctl -u yadreno-vpn -n 100 --no-pager
```

Если админка в Telegram всё ещё не появляется:

1. Проверьте `ADMIN_IDS` в `config.py` (должен быть ваш Telegram numeric ID).
2. Перезапустите сервис:

```bash
sudo systemctl restart yadreno-vpn
```
