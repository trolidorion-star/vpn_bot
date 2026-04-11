from typing import Dict, List, Optional, Tuple


CATALOG: Dict[str, Dict[str, object]] = {
    "social": {
        "title": "Соцсети",
        "apps": [
            {"id": "discord", "name": "Discord", "domains": ["discord.com", "discord.gg", "discordapp.com", "discordapp.net", "discordcdn.com"]},
            {"id": "telegram", "name": "Telegram", "domains": ["telegram.org", "t.me", "telegra.ph"]},
            {"id": "whatsapp", "name": "WhatsApp", "domains": ["whatsapp.com", "whatsapp.net"]},
            {"id": "viber", "name": "Viber", "domains": ["viber.com", "vibercdn.com"]},
            {"id": "signal", "name": "Signal", "domains": ["signal.org", "whispersystems.org"]},
            {"id": "instagram", "name": "Instagram", "domains": ["instagram.com", "cdninstagram.com"]},
            {"id": "facebook", "name": "Facebook", "domains": ["facebook.com", "fbcdn.net", "fbsbx.com"]},
            {"id": "x", "name": "X / Twitter", "domains": ["x.com", "twitter.com", "twimg.com"]},
            {"id": "reddit", "name": "Reddit", "domains": ["reddit.com", "redd.it", "redditmedia.com"]},
            {"id": "tiktok", "name": "TikTok", "domains": ["tiktok.com", "tiktokcdn.com", "muscdn.com"]},
        ],
    },
    "banks": {
        "title": "Банки",
        "apps": [
            {"id": "sber", "name": "Сбер", "domains": ["sberbank.ru", "sber.ru"]},
            {"id": "tinkoff", "name": "Т-Банк", "domains": ["tinkoff.ru", "tbank.ru"]},
            {"id": "vtb", "name": "ВТБ", "domains": ["vtb.ru"]},
            {"id": "alfa", "name": "Альфа-Банк", "domains": ["alfabank.ru", "alfa.ru"]},
            {"id": "raif", "name": "Райффайзен", "domains": ["raiffeisen.ru"]},
            {"id": "gazprom", "name": "Газпромбанк", "domains": ["gazprombank.ru"]},
        ],
    },
    "games": {
        "title": "Игры",
        "apps": [
            {"id": "steam", "name": "Steam", "domains": ["steampowered.com", "steamstatic.com", "steamcommunity.com"]},
            {"id": "epic", "name": "Epic Games", "domains": ["epicgames.com", "unrealengine.com"]},
            {"id": "riot", "name": "Riot", "domains": ["riotgames.com", "leagueoflegends.com", "valorant.com"]},
            {"id": "bnet", "name": "Battle.net", "domains": ["battle.net", "blizzard.com"]},
            {"id": "ea", "name": "EA App", "domains": ["ea.com", "origin.com"]},
            {"id": "genshin", "name": "Genshin", "domains": ["hoyoverse.com", "mihoyo.com"]},
        ],
    },
    "video": {
        "title": "Видео",
        "apps": [
            {"id": "youtube", "name": "YouTube", "domains": ["youtube.com", "ytimg.com", "googlevideo.com", "youtu.be"]},
            {"id": "twitch", "name": "Twitch", "domains": ["twitch.tv", "ttvnw.net", "jtvnw.net"]},
            {"id": "netflix", "name": "Netflix", "domains": ["netflix.com", "nflxvideo.net"]},
            {"id": "kinopoisk", "name": "Кинопоиск", "domains": ["kinopoisk.ru", "kinopoisk.dev"]},
            {"id": "ivi", "name": "IVI", "domains": ["ivi.ru"]},
            {"id": "okko", "name": "Okko", "domains": ["okko.tv"]},
        ],
    },
    "work": {
        "title": "Работа",
        "apps": [
            {"id": "github", "name": "GitHub", "domains": ["github.com", "githubusercontent.com", "githubassets.com"]},
            {"id": "openai", "name": "OpenAI", "domains": ["openai.com", "chatgpt.com"]},
            {"id": "notion", "name": "Notion", "domains": ["notion.so", "notion.site"]},
            {"id": "slack", "name": "Slack", "domains": ["slack.com", "slack-edge.com"]},
            {"id": "zoom", "name": "Zoom", "domains": ["zoom.us", "zoom.com"]},
            {"id": "teams", "name": "Microsoft Teams", "domains": ["teams.microsoft.com", "office.com", "microsoftonline.com"]},
        ],
    },
}

CATEGORY_ORDER = ["social", "banks", "games", "video", "work"]


def get_categories() -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    for key in CATEGORY_ORDER:
        cat = CATALOG.get(key, {})
        items.append((key, str(cat.get("title") or key)))
    return items


def get_apps_for_category(category: str) -> List[dict]:
    cat = CATALOG.get(category, {})
    return list(cat.get("apps", [])) if cat else []


def find_app(app_id: str) -> Optional[dict]:
    for _, cat in CATALOG.items():
        for app in cat.get("apps", []):
            if app.get("id") == app_id:
                return app
    return None
