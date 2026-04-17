from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from bot.services.exclusions_catalog import CATALOG


_EXTRA_RU_DOMAINS = {
    # Banks / finance
    "sberbank.ru", "sber.ru", "sberpay.ru", "sberbankonline.ru",
    "tbank.ru", "tinkoff.ru", "tinkoffjournal.ru", "api.tbank.ru",
    "vtb.ru", "online.vtb.ru", "alfabank.ru", "alfa.ru", "gazprombank.ru", "gpb.ru",
    "raiffeisen.ru", "rshb.ru", "pochtabank.ru", "psbank.ru", "sovcombank.ru",
    "akbars.ru", "ubrr.ru", "banki.ru", "mironline.ru", "nspk.ru", "sbp.nspk.ru",
    "yoomoney.ru", "qiwi.com",
    # State / critical services
    "gosuslugi.ru", "esia.gosuslugi.ru", "nalog.gov.ru", "fssp.gov.ru", "pfr.gov.ru",
    "mos.ru", "mosreg.ru", "gosuslugi.mosreg.ru", "lkfl2.nalog.ru", "zakupki.gov.ru",
    # Social / media RU
    "vk.com", "vk.ru", "ok.ru", "dzen.ru", "rutube.ru", "yappy.media",
    # Yandex ecosystem
    "yandex.ru", "ya.ru", "yandex.net", "yandexcloud.net", "kinopoisk.ru", "kinopoisk.dev",
    "music.yandex.ru", "taxi.yandex.ru", "market.yandex.ru", "eda.yandex.ru",
    "lavka.yandex.ru", "travel.yandex.ru", "360.yandex.ru", "disk.yandex.ru",
    # Mail/VK ecosystem
    "mail.ru", "my.mail.ru", "cloud.mail.ru", "vkvideo.ru", "xn--80asehdb",
    # Operators / infra
    "mts.ru", "beeline.ru", "megafon.ru", "tele2.ru", "yota.ru", "rostelecom.ru",
    # E-commerce / classifieds
    "ozon.ru", "wildberries.ru", "wb.ru", "avito.ru", "cian.ru", "youla.ru",
    "sbermegamarket.ru", "market.yandex.ru",
    # Delivery / city / transport
    "2gis.ru", "2gis.com", "rzd.ru", "aeroflot.ru", "s7.ru", "utair.ru",
    "pochta.ru", "dellin.ru", "cdek.ru",
    # Streaming / entertainment
    "ivi.ru", "okko.tv", "kion.ru", "wink.ru", "premier.one", "more.tv", "start.ru",
    # Messengers RU / platforms
    "max.ru", "icq.com", "tamtam.chat",
}


_EXTRA_RU_PACKAGES = {
    # Banks
    "ru.sberbankmobile", "ru.sberbankmobile.alpha", "ru.sberbank.online",
    "ru.tinkoff.mb", "com.idamob.tinkoff.android", "ru.vtb24.mobilebanking.android",
    "ru.alfabank.mobile.android", "ru.gazprombank.android.mobilebank.app",
    "ru.raiffeisennews", "ru.pochtabank.mobile", "ru.rshb.mbank", "com.psbank.psb",
    # State services
    "ru.gosuslugi.pos", "ru.rostel", "ru.mos.app", "ru.nalog.app", "ru.fssprus",
    # Social / media RU
    "com.vkontakte.android", "ru.ok.android", "ru.yandex.searchplugin", "ru.yandex.mail",
    "ru.rutube.app", "ru.max.app",
    # Yandex
    "ru.yandex.yandexmaps", "ru.yandex.taxi", "ru.yandex.market", "ru.yandex.disk",
    "ru.kinopoisk", "ru.yandex.music", "ru.yandex.browser",
    # E-commerce
    "ru.ozon.app.android", "com.wildberries.ru", "com.avito.android",
    # Operators
    "ru.mts", "ru.beeline.services", "ru.megafon.mlk", "ru.tele2.mytele2",
}


def _catalog_domains() -> Iterable[str]:
    # We include all bank apps + explicit RU video/social app domains from current catalog.
    include_categories = {"banks", "social", "video"}
    for cat_id, cat in CATALOG.items():
        if cat_id not in include_categories:
            continue
        for app in (cat.get("apps") or []):
            for domain in (app.get("domains") or []):
                value = str(domain or "").strip().lower()
                if value:
                    yield value


def _catalog_packages() -> Iterable[str]:
    include_categories = {"banks", "social", "video"}
    for cat_id, cat in CATALOG.items():
        if cat_id not in include_categories:
            continue
        for app in (cat.get("apps") or []):
            for pkg in (app.get("packages") or []):
                value = str(pkg or "").strip().lower()
                if value:
                    yield value


def _as_exclusion(rule_type: str, value: str) -> Dict[str, str]:
    return {"rule_type": rule_type, "rule_value": value}


def get_default_ru_exclusions() -> List[Dict[str, str]]:
    domains = sorted(set(_catalog_domains()) | {d.lower() for d in _EXTRA_RU_DOMAINS})
    packages = sorted(set(_catalog_packages()) | {p.lower() for p in _EXTRA_RU_PACKAGES})

    result: List[Dict[str, str]] = []
    result.extend(_as_exclusion("domain", d) for d in domains)
    result.extend(_as_exclusion("package", p) for p in packages)
    return result


def merge_with_default_ru_exclusions(exclusions: List[Dict[str, str]] | None) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    for item in get_default_ru_exclusions() + list(exclusions or []):
        rule_type = str(item.get("rule_type") or "").strip().lower()
        value = str(item.get("rule_value") or "").strip().lower()
        if rule_type not in {"domain", "package"} or not value:
            continue
        key = (rule_type, value)
        if key in seen:
            continue
        seen.add(key)
        merged.append({"rule_type": rule_type, "rule_value": value})

    return merged
