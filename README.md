<div align="center">

# 📦 ModsPort FOR STEAM

**Скачивай коллекции и моды из Steam Workshop для любой игры — без аккаунта и API-ключа.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/windows/)
[![Platform](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](#-быстрый-старт)
[![Dependencies](https://img.shields.io/badge/зависимости-нет-brightgreen)](#-как-это-работает)
[![SteamCMD](https://img.shields.io/badge/SteamCMD-anonymous-171A21?logo=steam&logoColor=white)](https://developer.valvesoftware.com/wiki/SteamCMD)
[![UI](https://img.shields.io/badge/интерфейс-русский-blue)](#)

[Быстрый старт](#-быстрый-старт) · [Возможности](#-возможности) · [Ограничения](#-важные-ограничения) · [FAQ](#-faq) · [English](#-english)

</div>

---

<!-- Сюда можно добавить скриншот программы:
<p align="center"><img src="screenshot.png" width="800" alt="ModsPort FOR STEAM"></p>
-->

## ✨ Возможности

| | |
|---|---|
| 🎮 **Любые игры** | Игра определяется автоматически по самому моду, название подтягивается из магазина Steam |
| 🔗 **Коллекции и одиночные моды** | Вставь ссылку на коллекцию или на один мод. Вложенные коллекции раскрываются, дубли убираются |
| 🔍 **Предпросмотр** | Кнопка «Проверить» покажет игру, название и список модов без скачивания |
| 📊 **Таблица со статусами** | У каждого мода свой статус: ожидает → скачивается 45% → готово / ошибка |
| 🧹 **Чистые логи** | Никакого мусора от SteamCMD. Подробный вывод включается галочкой, журнал каждого запуска сохраняется в отдельный файл |
| 💬 **Понятные ошибки** | Вместо `Access Denied` — «Steam не отдаёт этот мод без аккаунта» |
| ⚡ **Одна сессия SteamCMD** | Вся очередь качается за один вход, ошибка одного мода не останавливает остальные |
| 🪶 **Без зависимостей** | Только стандартная библиотека Python |

## 🚀 Быстрый старт

1. Установи [Python 3.10+](https://www.python.org/downloads/windows/). При установке отметь **Add python.exe to PATH** и компонент **tcl/tk**.
2. Скачай репозиторий (**Code → Download ZIP**) и распакуй **всю папку**.
3. Запусти **`Запустить.bat`**.
4. Вставь ссылку на коллекцию или мод из Steam Workshop, выбери папку и нажми **«Скачать»**.

> При первом запуске программа сама скачает официальный SteamCMD с сайта Valve.

## 📁 Что получится

```text
Папка загрузки/
└── Игра - Название коллекции (2026-11-06_13-00-00)/
    ├── 1234567890/            ← Workshop-элемент (его ID), структура как в Steam
    ├── 2345678901/
    ├── collection.json        ← отчёт по каждому моду
    └── КАК_ИСПОЛЬЗОВАТЬ.txt   ← краткая инструкция
```

Каждая загрузка создаёт **новую** папку: старые результаты никогда не перезаписываются.

## ⚠️ Важные ограничения

- **Только Steam Workshop.** Nexus Mods, CurseForge и другие сайты не поддерживаются.
- **Вход анонимный.** Многие игры не отдают Workshop без аккаунта — такие моды получат ошибку в таблице, остальные продолжат скачиваться. Программа **не обходит** это ограничение.
- Частные, скрытые и удалённые моды недоступны.
- Программа **только скачивает** файлы. Она не устанавливает и не включает моды в игре: как их подключать, зависит от игры (смотри описание мода).
- EXE, DLL и скрипты из модов программа **не запускает**. Моды — сторонний код, ставь только от авторов, которым доверяешь.
- Программа не скачивает саму игру и не проверяет и не обходит владение ею.

## 🛠 Как это работает

1. Список модов берётся из публичного Steam Web API (ключ не нужен).
2. Для каждого мода определяется игра (`consumer_app_id`).
3. Официальный `steamcmd.exe` входит как `anonymous` и скачивает всю очередь одной сессией (`workshop_download_item`).
4. Успехом считается только сообщение SteamCMD об успешной загрузке. Файлы копируются в отдельную папку результата.

Где что лежит:

| Что | Где |
|---|---|
| SteamCMD и его кэш | `%PUBLIC%\PZCollectionLoader\steamcmd` |
| Настройки | `%LOCALAPPDATA%\PZCollectionLoader\settings.json` |
| Журналы (последние 10) | `%LOCALAPPDATA%\PZCollectionLoader\logs` |

Кэш SteamCMD остаётся после копирования: нужно место под кэш **и** под результат. Когда кэш не нужен, его можно удалить целиком.

## ❓ FAQ

<details>
<summary><b>Окно не открывается</b></summary>

Открой `Запустить.bat` и прочитай сообщение в консоли. Чаще всего не установлен Python или компонент tcl/tk — переустанови Python с этой галочкой.
</details>

<details>
<summary><b>Мод получил ошибку «нужен аккаунт»</b></summary>

Это ограничение Steam для данной игры или мода при анонимном входе. Обойти его нельзя.
</details>

<details>
<summary><b>Где посмотреть подробности ошибки?</b></summary>

Включи галочку «Подробный вывод SteamCMD» или нажми «Файл журнала». Журналы могут содержать локальные пути — проверь их перед отправкой кому-либо.
</details>

<details>
<summary><b>Можно остановить загрузку?</b></summary>

Да, кнопка «Остановить» завершает SteamCMD. Уже скопированные моды сохраняются.
</details>

## 🌍 English

**ModsPort FOR STEAM** is a small Windows GUI that downloads Steam Workshop collections and single mods for **any game** through anonymous SteamCMD. No Steam account and no API key required. Pure Python 3.10+, standard library only.

- Auto-detects the game, previews the mod list before downloading
- Per-mod status table, clean logs, readable error messages
- Whole queue in a single SteamCMD session; one failed mod doesn't stop the rest
- Anonymous access only: games that require an account for Workshop downloads will fail for those mods (this is not bypassed)

**Quick start:** install Python 3.10+ (with tcl/tk and PATH), unpack the repo, run `Запустить.bat`, paste a Workshop link, pick a folder, press **Скачать** (Download). The UI is in Russian.

## ⚖️ Дисклеймер

Проект неофициальный и не связан с Valve Corporation. Steam и SteamCMD — торговые марки Valve. Используй программу только для загрузки контента, на который у тебя есть право, и соблюдай правила Steam и авторов модов.
