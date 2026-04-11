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
            {"id": "snapchat", "name": "Snapchat", "domains": ["snapchat.com", "sc-cdn.net"]},
            {"id": "pinterest", "name": "Pinterest", "domains": ["pinterest.com", "pinimg.com"]},
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
            {"id": "roblox", "name": "Roblox", "domains": ["roblox.com", "rbxcdn.com"]},
            {"id": "minecraft", "name": "Minecraft", "domains": ["minecraft.net", "mojang.com"]},
            {"id": "pubg", "name": "PUBG", "domains": ["pubg.com", "krafton.com"]},
            {"id": "warface", "name": "Warface", "domains": ["warface.com", "my.games"]},
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
            {"id": "rutube", "name": "RuTube", "domains": ["rutube.ru"]},
            {"id": "premier", "name": "Premier", "domains": ["premier.one"]},
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
            {"id": "figma", "name": "Figma", "domains": ["figma.com"]},
            {"id": "miro", "name": "Miro", "domains": ["miro.com"]},
            {"id": "jira", "name": "Jira/Confluence", "domains": ["atlassian.com", "jira.com"]},
        ],
    },
    "adult": {
        "title": "18+",
        "apps": [
            {"id": "pornhub", "name": "Pornhub", "domains": ["pornhub.com", "phncdn.com"]},
            {"id": "xvideos", "name": "XVideos", "domains": ["xvideos.com", "xvideos-cdn.com"]},
            {"id": "xnxx", "name": "XNXX", "domains": ["xnxx.com", "xnxx-cdn.com"]},
            {"id": "xhamster", "name": "xHamster", "domains": ["xhamster.com", "xhcdn.com"]},
            {"id": "youporn", "name": "YouPorn", "domains": ["youporn.com"]},
            {"id": "redtube", "name": "RedTube", "domains": ["redtube.com"]},
            {"id": "tube8", "name": "Tube8", "domains": ["tube8.com"]},
            {"id": "spankbang", "name": "SpankBang", "domains": ["spankbang.com"]},
            {"id": "chaturbate", "name": "Chaturbate", "domains": ["chaturbate.com"]},
            {"id": "stripchat", "name": "Stripchat", "domains": ["stripchat.com"]},
            {"id": "onlyfans", "name": "OnlyFans", "domains": ["onlyfans.com"]},
            {"id": "fansly", "name": "Fansly", "domains": ["fansly.com"]},
        ],
    },
}

CATEGORY_ORDER = ["social", "banks", "games", "video", "work", "adult"]


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
