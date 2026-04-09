#!/bin/bash
cd /root/my-private
echo "🔄 Синхронизация с GitHub..."
git pull origin main
if [[ -n $(git status -s) ]]; then
    echo "📤 Обнаружены изменения, отправляем в репозиторий..."
    git add .
    git commit -m "Auto sync: $(date '+%Y-%m-%d %H:%M:%S')"
    git push
else
    echo "✅ Всё актуально, изменений нет"
fi
