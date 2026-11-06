# -*- coding: utf-8 -*-
"""Модопорт 2.0 — Steam Workshop для любых игр.
Windows / Python 3.10+. Только стандартная библиотека. SteamCMD, anonymous."""
from __future__ import annotations

import codecs
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = 'Модопорт'
VERSION = '2.0'
STEAM_ZIP = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip'
API = 'https://api.steampowered.com/ISteamRemoteStorage/'
STORE_API = 'https://store.steampowered.com/api/appdetails'
USER_AGENT = {'User-Agent': 'Modoport/2.0'}
STATE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PZCollectionLoader'
STATE.mkdir(parents=True, exist_ok=True)
CONFIG = STATE / 'settings.json'
LOGS = STATE / 'logs'
# Public avoids Cyrillic usernames in SteamCMD's own working directory.
CACHE = Path(os.environ.get('PUBLIC', str(STATE))) / 'PZCollectionLoader' / 'steamcmd'

# Палитра: спокойный тёмно-серый с одним синим акцентом.
BG, PANEL, PANEL2, LINE = '#16191f', '#1e222a', '#252a34', '#2f3541'
FG, MUTED, ACCENT, ACCENT_HI = '#e4e8ee', '#8a93a3', '#4a90e2', '#68a5ee'
OK, FAIL, BUSY = '#6fcf97', '#ee7b7b', '#6aa8f7'

# Строки прогресса SteamCMD — чистый шум, в журнал не попадают вообще.
PROGRESS = re.compile(r'^(\[\s*\d+%\]|\[-+\]|Update state)', re.I)

ERROR_HINTS = (
    ('access denied', 'Steam не отдаёт этот мод без аккаунта'),
    ('no subscription', 'Для загрузки нужен аккаунт с этой игрой'),
    ('file not found', 'Файл мода не найден в Steam'),
    ('timeout', 'Превышено время ожидания Steam'),
    ('no connection', 'Нет соединения со Steam'),
    ('disk write', 'Ошибка записи на диск'),
    ('not enough disk', 'Не хватает места на диске'),
    ('failure', 'Steam отказал в загрузке'),
)


class Cancelled(Exception):
    pass


def api(method, fields):
    request = urllib.request.Request(
        API + method + '/v1/',
        data=urllib.parse.urlencode(fields).encode('ascii'),
        headers=USER_AGENT,
    )
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)['response']
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError(f'Не удалось связаться со Steam API: {last}')


def game_name(app_id):
    """Название игры из магазина Steam; при любой проблеме — просто App ID."""
    try:
        req = urllib.request.Request(f'{STORE_API}?appids={app_id}&filters=basic', headers=USER_AGENT)
        with urllib.request.urlopen(req, timeout=10) as response:
            entry = json.load(response).get(str(app_id), {})
        if entry.get('success'):
            return entry['data'].get('name') or f'App {app_id}'
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        pass
    return f'App {app_id}'


def parse_id(text):
    text = text.strip()
    if re.fullmatch(r'[0-9]{1,20}', text):
        return text
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme != 'https' or parsed.hostname not in ('steamcommunity.com', 'www.steamcommunity.com'):
        raise ValueError('Нужна HTTPS-ссылка steamcommunity.com на коллекцию или мод (или числовой ID).')
    item_id = urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
    if not re.fullmatch(r'[0-9]{1,20}', item_id):
        raise ValueError('В ссылке нет корректного параметра id.')
    return item_id


def safe_name(text, limit=60):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip(' .')[:limit].strip(' .') or 'collection'


def size_text(value):
    try:
        number = float(int(value))
    except (TypeError, ValueError):
        return ''
    if number <= 0:
        return ''
    for unit in ('Б', 'КБ', 'МБ'):
        if number < 1024:
            return f'{number:.0f} {unit}' if unit == 'Б' else f'{number:.1f} {unit}'
        number /= 1024
    return f'{number:.1f} ГБ'


def explain(raw):
    """Короткая человеческая причина вместо технического сообщения SteamCMD."""
    low = raw.lower()
    for key, text in ERROR_HINTS:
        if key in low:
            return text
    return raw if len(raw) <= 90 else raw[:87] + '…'


def howto_text(game_names, app_ids):
    games = ', '.join(game_names) if game_names else 'выбранной игры'
    text = (
        f'Это файлы Steam Workshop: {games}. Программа только скачивает их — ничего не устанавливает\n'
        'и не включает в игре.\n\n'
        'Каждая числовая папка — отдельный Workshop-элемент (его ID). Структура сохранена как в Steam.\n'
        'Как подключать моды, зависит от игры: у многих есть собственная папка mods, у других моды\n'
        'берутся только из Workshop. Смотри описание мода и инструкцию автора.\n'
        'Порядок загрузки и совместимость проверяются отдельно; порядок в коллекции — не порядок загрузки.\n'
        'EXE, DLL и скрипты из модов программа не запускает. Моды — сторонний код: доверяй только авторам,\n'
        'которым доверяешь.\n'
        'Отчёт collection.json содержит результат по каждому элементу.\n'
        'Блокировку анонимного доступа Steam программа не обходит.\n'
    )
    if '108600' in app_ids:
        text += (
            '\nProject Zomboid: закрой игру, открой у элемента папку mods и скопируй находящиеся В НЕЙ\n'
            'папки модов целиком в %USERPROFILE%\\Zomboid\\mods, сохраняя вложенность (например B42/common).\n'
            'Не копируй числовые папки Workshop целиком. Затем включи моды в игре.\n'
        )
    return text


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP_NAME} {VERSION} — Steam Workshop')
        self.geometry('1000x740')
        self.minsize(840, 620)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.proc = None
        self.proc_lock = threading.Lock()
        self.output = None
        self.lock_file = None
        self.log_file = None
        self.log_path = None
        self.log_lock = threading.Lock()
        self.verbose = False
        self.rows = {}
        self.full_validate = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        self.verbose_var.trace_add('write', lambda *a: setattr(self, 'verbose', bool(self.verbose_var.get())))
        self.link = tk.StringVar(value='')
        self.folder = tk.StringVar(value=str(Path.home() / 'Downloads' / 'Workshop'))
        try:
            settings = json.loads(CONFIG.read_text(encoding='utf-8'))
            self.folder.set(settings.get('folder', self.folder.get()))
            self.link.set(settings.get('link', ''))
            self.full_validate.set(bool(settings.get('validate', False)))
            self.verbose_var.set(bool(settings.get('verbose', False)))
        except (OSError, ValueError):
            pass
        self.status = tk.StringVar(value='Готов к работе')
        self.counter = tk.StringVar(value='')
        self.info = tk.StringVar(value='Вставь ссылку на коллекцию или отдельный мод из Steam Workshop — игра определится сама.')
        self.build_ui()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.drain)

    # ---------- интерфейс ----------
    def build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background=BG, foreground=FG)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Field.TLabel', foreground=MUTED, font=('Segoe UI', 10))
        style.configure('Head.TLabel', font=('Segoe UI Semibold', 15))
        style.configure('Status.TLabel', font=('Segoe UI Semibold', 10))
        style.configure('TCheckbutton', background=BG, foreground=MUTED)
        style.map('TCheckbutton', background=[('active', BG)], foreground=[('active', FG)])
        style.configure('TEntry', fieldbackground=PANEL, foreground=FG, insertcolor=FG, bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, padding=7)
        style.map('TEntry', bordercolor=[('focus', ACCENT)], lightcolor=[('focus', ACCENT)], darkcolor=[('focus', ACCENT)])
        style.configure('TButton', background=PANEL2, foreground=FG, padding=(14, 7), borderwidth=0, focuscolor=PANEL2)
        style.map('TButton', background=[('active', LINE), ('disabled', PANEL)], foreground=[('disabled', '#5d6676')])
        style.configure('Accent.TButton', background=ACCENT, foreground='#ffffff', font=('Segoe UI Semibold', 10), focuscolor=ACCENT)
        style.map('Accent.TButton', background=[('active', ACCENT_HI), ('disabled', '#2c3d54')], foreground=[('disabled', '#7f8da3')])
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=PANEL, borderwidth=0, thickness=6)
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=27,
                        borderwidth=0, font=('Segoe UI', 10))
        style.map('Treeview', background=[('selected', '#2c3a52')], foreground=[('selected', FG)])
        style.configure('Treeview.Heading', background=PANEL2, foreground=MUTED, relief='flat',
                        font=('Segoe UI Semibold', 9), padding=(8, 6))
        style.map('Treeview.Heading', background=[('active', PANEL2)])
        style.configure('Vertical.TScrollbar', background=PANEL2, troughcolor=PANEL, borderwidth=0, arrowcolor=MUTED)

        root = ttk.Frame(self, padding=(22, 16, 22, 16))
        root.pack(fill='both', expand=True)

        head = ttk.Frame(root)
        head.pack(fill='x', pady=(0, 14))
        ttk.Label(head, text=APP_NAME, style='Head.TLabel').pack(side='left')
        ttk.Label(head, text=f'v{VERSION}  ·  Steam Workshop, любые игры', style='Muted.TLabel').pack(side='left', padx=(12, 0), pady=(5, 0))

        form = ttk.Frame(root)
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text='Ссылка', style='Field.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 12), pady=(0, 8))
        self.link_entry = ttk.Entry(form, textvariable=self.link)
        self.link_entry.grid(row=0, column=1, sticky='ew', pady=(0, 8))
        self.paste_btn = ttk.Button(form, text='Вставить', command=self.paste_link)
        self.paste_btn.grid(row=0, column=2, padx=(8, 0), pady=(0, 8))
        self.check_btn = ttk.Button(form, text='Проверить', command=lambda: self.begin(True))
        self.check_btn.grid(row=0, column=3, padx=(8, 0), pady=(0, 8))
        ttk.Label(form, text='Папка', style='Field.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 12))
        self.folder_entry = ttk.Entry(form, textvariable=self.folder)
        self.folder_entry.grid(row=1, column=1, columnspan=2, sticky='ew')
        self.browse = ttk.Button(form, text='Обзор…', command=self.choose)
        self.browse.grid(row=1, column=3, padx=(8, 0))
        self.link_entry.bind('<Return>', lambda e: self.begin(True))

        tk.Label(root, textvariable=self.info, bg=PANEL, fg=MUTED, font=('Segoe UI', 10), anchor='w',
                 justify='left', padx=14, pady=9, wraplength=900).pack(fill='x', pady=(14, 10))

        table = ttk.Frame(root)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('title', 'id', 'size', 'status'), show='headings', selectmode='browse')
        for col, text, width, stretch in (('title', 'Мод', 380, True), ('id', 'Workshop ID', 110, False),
                                          ('size', 'Размер', 80, False), ('status', 'Статус', 300, True)):
            self.tree.heading(col, text=text, anchor='w')
            self.tree.column(col, width=width, stretch=stretch, anchor='w')
        for tag, color in (('wait', MUTED), ('busy', BUSY), ('ok', OK), ('fail', FAIL)):
            self.tree.tag_configure(tag, foreground=color)
        bar = ttk.Scrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')

        ttk.Label(root, textvariable=self.status, style='Status.TLabel').pack(anchor='w', pady=(12, 5))
        self.progress = ttk.Progressbar(root, mode='determinate', maximum=1)
        self.progress.pack(fill='x')
        ttk.Label(root, textvariable=self.counter, style='Muted.TLabel').pack(anchor='w', pady=(5, 10))

        row = ttk.Frame(root)
        row.pack(fill='x')
        self.start_btn = ttk.Button(row, text='Скачать', style='Accent.TButton', command=lambda: self.begin(False))
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(row, text='Остановить', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=8)
        ttk.Button(row, text='Открыть папку', command=self.open_folder).pack(side='right')
        ttk.Button(row, text='Файл журнала', command=self.open_log_file).pack(side='right', padx=8)
        self.log_toggle = ttk.Button(row, text='Скрыть журнал', command=self.toggle_log)
        self.log_toggle.pack(side='right')

        opts = ttk.Frame(root)
        opts.pack(fill='x', pady=(8, 8))
        self.validate_check = ttk.Checkbutton(opts, text='Полная проверка файлов (медленнее)', variable=self.full_validate)
        self.validate_check.pack(side='left')
        self.verbose_check = ttk.Checkbutton(opts, text='Подробный вывод SteamCMD', variable=self.verbose_var)
        self.verbose_check.pack(side='left', padx=(18, 0))

        self.log_box = ttk.Frame(root)
        self.log_box.pack(fill='x')
        self.log = tk.Text(self.log_box, height=6, bg='#10131a', fg='#b9c3d3', font=('Consolas', 9), relief='flat',
                           padx=10, pady=8, wrap='word', state='disabled', insertbackground=FG)
        self.log.pack(side='left', fill='x', expand=True)
        log_bar = ttk.Scrollbar(self.log_box, command=self.log.yview)
        log_bar.pack(side='right', fill='y')
        self.log.configure(yscrollcommand=log_bar.set)
        self.log.tag_configure('err', foreground=FAIL)
        self.log.tag_configure('good', foreground=OK)

        self.entries = (self.folder_entry, self.link_entry)
        self.locked_widgets = (self.folder_entry, self.link_entry, self.browse, self.paste_btn,
                               self.validate_check, self.verbose_check)
        for entry in self.entries:
            entry.bind('<Control-a>', lambda e: (e.widget.select_range(0, 'end'), 'break')[-1])
        # Keycodes keep Ctrl+C/V/X/A working even with the Russian keyboard layout.
        self.bind_all('<Control-KeyPress>', self.shortcuts, add='+')

    def shortcuts(self, event):
        widget = event.widget
        if not isinstance(widget, (ttk.Entry, tk.Text)):
            return
        # На латинской раскладке Tk сам вставляет/копирует по Ctrl+V/C/X — повторно
        # генерировать действие нельзя, иначе текст вставится дважды.
        if event.keysym.lower() in ('c', 'v', 'x', 'a'):
            return
        action = {67: '<<Copy>>', 86: '<<Paste>>', 88: '<<Cut>>'}.get(event.keycode)
        if action:
            widget.event_generate(action)
            return 'break'
        if event.keycode == 65 and isinstance(widget, ttk.Entry):
            widget.select_range(0, 'end')
            return 'break'

    def toggle_log(self):
        if self.log_box.winfo_ismapped():
            self.log_box.pack_forget()
            self.log_toggle.configure(text='Показать журнал')
        else:
            self.log_box.pack(fill='x')
            self.log_toggle.configure(text='Скрыть журнал')

    def paste_link(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return
        if text:
            self.link.set(text)

    def choose(self):
        selected = filedialog.askdirectory(title='Куда сохранить?')
        if selected:
            self.folder.set(selected)

    def open_folder(self):
        path = self.output or Path(self.folder.get()).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror('Не удалось открыть папку', str(exc))

    def open_log_file(self):
        try:
            if self.log_path and self.log_path.exists():
                os.startfile(str(self.log_path))
            else:
                LOGS.mkdir(parents=True, exist_ok=True)
                os.startfile(str(LOGS))
        except OSError as exc:
            messagebox.showerror('Не удалось открыть журнал', str(exc))

    def set_busy(self, busy):
        state = 'disabled' if busy else 'normal'
        for widget in self.locked_widgets:
            widget.configure(state=state)
        self.start_btn.configure(state=state)
        self.check_btn.configure(state=state)
        self.stop_btn.configure(state='normal' if busy else 'disabled')

    # ---------- журнал ----------
    def open_log(self):
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            for old in sorted(LOGS.glob('run_*.log'))[:-9]:
                old.unlink(missing_ok=True)
            self.log_path = LOGS / time.strftime('run_%Y%m%d_%H%M%S.log')
            with self.log_lock:
                self.log_file = self.log_path.open('a', encoding='utf-8')
        except OSError:
            self.log_file = None

    def close_log(self):
        with self.log_lock:
            if self.log_file:
                try:
                    self.log_file.close()
                except OSError:
                    pass
                self.log_file = None

    def say(self, text, kind='info', raw=False):
        """Журнал: в файл идёт всё, кроме строк прогресса; в окно — только значимое
        (сырой вывод SteamCMD — лишь при включённом «Подробном выводе»)."""
        stamp = time.strftime('%H:%M:%S')
        with self.log_lock:
            if self.log_file:
                try:
                    self.log_file.write(f'{stamp}  {text}\n')
                    self.log_file.flush()
                except OSError:
                    pass
        if not raw or self.verbose:
            self.events.put(('log', (stamp, text, kind)))

    def emit(self, kind, *values):
        self.events.put((kind, values))

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    # ---------- запуск / остановка ----------
    def save_settings(self):
        CONFIG.write_text(json.dumps({
            'folder': self.folder.get(), 'link': self.link.get(),
            'validate': bool(self.full_validate.get()), 'verbose': bool(self.verbose_var.get()),
        }, ensure_ascii=False, indent=2), encoding='utf-8')

    def begin(self, preview):
        if self.running:
            return
        try:
            root_id = parse_id(self.link.get())
            target = None
            if not preview:
                if not self.folder.get().strip():
                    raise ValueError('Выбери папку для скачивания.')
                target = Path(self.folder.get()).expanduser().resolve()
                target.mkdir(parents=True, exist_ok=True)
                cache = CACHE.resolve()
                if target == cache or cache in target.parents or target in cache.parents:
                    raise ValueError('Папка загрузки не должна пересекаться с папкой SteamCMD.')
            self.save_settings()
        except (OSError, ValueError) as exc:
            messagebox.showerror('Проверь настройки', str(exc))
            return
        self.cancel.clear()
        self.output = None
        self.running = True
        self.open_log()
        self.set_busy(True)
        self.progress.configure(value=0, maximum=1)
        self.counter.set('')
        self.status.set('Получаем данные из Steam…')
        threading.Thread(target=self.worker, args=(root_id, target, bool(self.full_validate.get()), preview), daemon=True).start()

    def stop(self):
        self.cancel.set()
        self.status.set('Останавливаем…')
        self.stop_btn.configure(state='disabled')
        threading.Thread(target=self.kill_process, daemon=True).start()

    def kill_process(self):
        with self.proc_lock:
            proc = self.proc
            if proc and proc.poll() is None:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)

    # ---------- Steam: состав коллекции ----------
    def get_items(self, root_id):
        """Возвращает (items, info). Работает и для коллекции, и для одиночного мода."""
        seen, items = set(), {}

        def visit(cid, depth):
            self.check()
            if cid in seen:
                return True
            if depth > 20 or len(seen) > 500:
                raise RuntimeError('Слишком много вложенных коллекций.')
            seen.add(cid)
            data = api('GetCollectionDetails', {'collectioncount': 1, 'publishedfileids[0]': cid})
            details = data.get('collectiondetails') or []
            children = details[0].get('children', []) if details and details[0].get('result') == 1 else []
            if not children:
                return depth > 0  # корень без детей — вероятно, одиночный мод
            for child in children:
                ident = str(child['publishedfileid'])
                if not re.fullmatch(r'[0-9]{1,20}', ident):
                    raise RuntimeError('Steam вернул некорректный ID.')
                if int(child.get('filetype', 0)) == 2:
                    visit(ident, depth + 1)
                else:
                    items.setdefault(ident, {'id': ident})
            return True

        single = not visit(root_id, 0)
        if single:
            items[root_id] = {'id': root_id}
        ids = list(items)
        for offset in range(0, len(ids), 100):
            self.check()
            batch = ids[offset:offset + 100]
            fields = {'itemcount': len(batch)}
            fields.update({f'publishedfileids[{i}]': ident for i, ident in enumerate(batch)})
            data = api('GetPublishedFileDetails', fields)
            for detail in data.get('publishedfiledetails', []):
                ident = str(detail['publishedfileid'])
                if ident not in items:
                    continue
                item = items[ident]
                item['title'] = detail.get('title') or ident
                item['size'] = detail.get('file_size')
                app = str(detail.get('consumer_app_id') or '')
                if detail.get('result') != 1:
                    item['blocked'] = 'Описание недоступно: мод скрыт, удалён или ограничен.'
                elif single and int(detail.get('file_type', 0)) == 2:
                    raise RuntimeError('Коллекция пуста или недоступна. Проверь ссылку и публичность.')
                elif not app.isdigit() or app == '0':
                    item['blocked'] = 'Steam не указал, к какой игре относится элемент.'
                else:
                    item['app'] = app
                    item['verified'] = True
        for item in items.values():
            if not item.get('verified'):
                item.setdefault('blocked', 'Steam не подтвердил игру для этого элемента.')
        if not any(item.get('verified') for item in items.values()):
            raise RuntimeError('Не найдено ни одного доступного мода. Проверь ссылку и публичность.')

        title = None
        if not single:
            try:
                data = api('GetPublishedFileDetails', {'itemcount': 1, 'publishedfileids[0]': root_id})
                title = (data.get('publishedfiledetails') or [{}])[0].get('title')
            except RuntimeError:
                pass
        elif items[root_id].get('title'):
            title = items[root_id]['title']
        apps = {}
        for item in items.values():
            if item.get('app') and item['app'] not in apps:
                self.check()
                apps[item['app']] = game_name(item['app'])
        return list(items.values()), {'title': title or root_id, 'apps': apps, 'single': single}

    # ---------- SteamCMD ----------
    def prepare_steamcmd(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        exe = CACHE / 'steamcmd.exe'
        if exe.exists():
            return exe
        self.emit('status', 'Скачиваем официальный SteamCMD…')
        self.say('Первый запуск: скачиваю SteamCMD с сайта Valve.')
        archive = CACHE / 'steamcmd.download'
        try:
            req = urllib.request.Request(STEAM_ZIP, headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=60) as response, archive.open('wb') as out:
                while True:
                    self.check()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            with zipfile.ZipFile(archive) as bundle:
                base = CACHE.resolve()
                for info in bundle.infolist():
                    destination = (base / info.filename).resolve()
                    if base not in destination.parents:
                        raise RuntimeError('Небезопасный путь в архиве SteamCMD.')
                bundle.extractall(CACHE)
        finally:
            archive.unlink(missing_ok=True)
        if not exe.is_file():
            raise RuntimeError('В официальном архиве не найден steamcmd.exe.')
        return exe

    def download_batch(self, exe, items, validate, on_result):
        """Одна сессия SteamCMD на всю очередь; результат по каждому моду обрабатывается отдельно."""
        self.check()
        wanted = {item['id'] for item in items}
        if not wanted:
            return
        apps = {item['id']: item['app'] for item in items}
        titles = {item['id']: item.get('title', item['id']) for item in items}
        script = CACHE / ('queue_' + uuid.uuid4().hex + '.txt')
        commands = ['@ShutdownOnFailedCommand 0', '@NoPromptForPassword 1', 'login anonymous']
        commands += [f"workshop_download_item {item['app']} {item['id']}" + (' validate' if validate else '') for item in items]
        commands.append('quit')
        script.write_text('\n'.join(commands) + '\n', encoding='ascii')
        lines = queue.Queue()
        completed = set()
        tail = []
        proc = None
        current, last_pct = None, -1
        last_output = time.monotonic()

        def reader():
            # Split CR and LF, including bootstrapper output without normal newlines.
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            buffer = ''
            try:
                while True:
                    chunk = os.read(proc.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    lines.put(('activity', None))
                    buffer += decoder.decode(chunk)
                    parts = re.split(r'[\r\n]', buffer)
                    buffer = parts.pop()
                    for line in parts:
                        if line.strip():
                            lines.put(('line', line.strip()))
                buffer += decoder.decode(b'', final=True)
                if buffer.strip():
                    lines.put(('line', buffer.strip()))
            except Exception as exc:
                lines.put(('reader_error', str(exc)))
            finally:
                proc.stdout.close()
                lines.put(('eof', None))

        try:
            with self.proc_lock:
                self.check()
                proc = subprocess.Popen([str(exe), '+runscript', str(script)], cwd=str(CACHE),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                self.proc = proc
            threading.Thread(target=reader, daemon=True).start()
            while True:
                self.check()
                try:
                    kind, line = lines.get(timeout=0.25)
                except queue.Empty:
                    if time.monotonic() - last_output > 1200:
                        raise RuntimeError('SteamCMD не выдаёт данных 20 минут. Проверь сеть и повтори.')
                    continue
                last_output = time.monotonic()
                if kind == 'eof':
                    break
                if kind == 'reader_error':
                    raise RuntimeError('Не удалось прочитать вывод SteamCMD: ' + line)
                if kind == 'activity':
                    continue
                if PROGRESS.match(line):
                    # Процент показываем в таблице, в журнал строки прогресса не пишем.
                    pct = re.search(r'progress:\s*([\d.]+)', line)
                    if pct and current and 'downloading' in line.lower():
                        value = int(float(pct[1]))
                        if value != last_pct:
                            last_pct = value
                            self.emit('row', current, f'Скачивается {value}%', 'busy')
                    continue
                tail.append(line)
                tail = tail[-12:]
                self.say('SteamCMD: ' + line, raw=True)
                if re.search(r'Logged in OK', line, re.I):
                    self.say('Вход в Steam выполнен (anonymous).')
                downloading = re.search(r'Downloading item\s+(\d+)', line, re.I)
                if downloading and downloading[1] in wanted:
                    current, last_pct = downloading[1], -1
                    self.emit('status', 'Скачивание: ' + titles[current])
                    self.emit('row', current, 'Скачивается…', 'busy')
                for match in re.finditer(r'Success\. Downloaded item\s+(\d+)\b', line, re.I):
                    ident = match[1]
                    if ident in wanted and ident not in completed:
                        source = CACHE / 'steamapps' / 'workshop' / 'content' / apps[ident] / ident
                        if source.is_dir() and any(source.iterdir()):
                            on_result(ident, source, None)
                        else:
                            on_result(ident, None, 'SteamCMD сообщил успех, но папка мода отсутствует или пуста.')
                        completed.add(ident)
                failure = re.search(r'ERROR!\s*Download item\s+(\d+)\s+failed[^\r\n]*', line, re.I)
                if failure and failure[1] in wanted and failure[1] not in completed:
                    on_result(failure[1], None, failure[0])
                    completed.add(failure[1])
            returncode = proc.wait(timeout=30)
            # Ненулевой общий код не отменяет уже подтверждённые загрузки.
            if returncode:
                self.say(f'SteamCMD завершился с кодом {returncode}; подтверждённые моды сохранены.', raw=True)
            for item in items:
                self.check()
                if item['id'] not in completed:
                    on_result(item['id'], None, 'SteamCMD не подтвердил загрузку. Последний вывод: ' + ' | '.join(tail[-3:]))
        finally:
            if proc is not None and proc.poll() is None:
                self.kill_process()
            with self.proc_lock:
                if self.proc is proc:
                    self.proc = None
            script.unlink(missing_ok=True)

    def copy_item(self, source, output, ident):
        destination = output / ident
        # Никогда не сливаем и не удаляем существующую папку пользователя.
        if destination.exists():
            raise RuntimeError('Папка с таким ID уже существует без записи в отчёте. Выбери новую папку.')
        stage = output / ('.partial-' + ident + '-' + uuid.uuid4().hex)

        def copy_checked(src, dst):
            self.check()
            return shutil.copy2(src, dst)

        try:
            shutil.copytree(source, stage, copy_function=copy_checked)
            self.check()
            stage.rename(destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    # ---------- основной поток ----------
    def worker(self, root_id, target, validate, preview):
        report = None
        output = None
        try:
            items, info = self.get_items(root_id)
            apps = info['apps']
            games = ', '.join(apps.values()) or 'неизвестная игра'
            usable = sum(1 for item in items if item.get('verified'))
            blocked = len(items) - usable
            summary = f'{games}  •  {info["title"]}  •  {"мод" if info["single"] else "модов"}: {len(items)}'
            if blocked:
                summary += f'  (недоступно: {blocked})'
            self.emit('info', summary)
            rows = []
            for item in items:
                status = ('Недоступен: ' + item['blocked']) if item.get('blocked') else ('Доступен' if preview else 'Ожидает')
                rows.append((item['id'], item.get('title', item['id']), size_text(item.get('size')), status,
                             'fail' if item.get('blocked') else 'wait'))
            self.emit('items', rows)
            self.say(f'Игра: {games}. Элементов: {len(items)}, доступно: {usable}.')
            if preview:
                self.emit('status', 'Проверка завершена. Нажми «Скачать», чтобы загрузить моды.')
                return

            import msvcrt
            # OS lock also protects against another instance sharing SteamCMD.
            self.lock_file = (STATE / 'download.lock').open('a+b')
            self.lock_file.seek(0)
            if not self.lock_file.read(1):
                self.lock_file.write(b'0')
                self.lock_file.flush()
            self.lock_file.seek(0)
            try:
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('Другая копия программы уже использует SteamCMD. Закрой её или дождись завершения.')

            stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
            base_name = f'{safe_name(next(iter(apps.values()), "Workshop"), 40)} - {safe_name(info["title"], 50)} ({stamp})'
            output = target / base_name
            if output.exists():
                output = target / f'{base_name}-{uuid.uuid4().hex[:4]}'
            output.mkdir(parents=True, exist_ok=False)
            self.output = output
            report = {'collection_id': root_id, 'title': info['title'], 'games': apps,
                      'source': f'https://steamcommunity.com/sharedfiles/filedetails/?id={root_id}',
                      'items': items, 'state': 'running'}
            self.save_report(output, report)
            self.say(f'Папка результата: {output}')
            self.emit('progress', 0, len(items), 0, 0)
            good, bad, processed = 0, 0, 0
            by_id = {item['id']: item for item in items}

            def record(ident, source, error):
                nonlocal good, bad, processed
                self.check()
                item = by_id[ident]
                title = item.get('title', ident)
                try:
                    if error:
                        raise RuntimeError(error)
                    self.emit('status', 'Сохраняем: ' + title)
                    self.emit('row', ident, 'Копируется…', 'busy')
                    self.copy_item(source, output, ident)
                    item['status'] = 'downloaded'
                    good += 1
                    self.emit('row', ident, 'Готово', 'ok')
                    self.say(f'Готово: {title}', 'good')
                except Cancelled:
                    item['status'] = 'cancelled'
                    raise
                except Exception as exc:
                    raw = str(exc)
                    item['status'], item['error'] = 'failed', explain(raw)
                    item['error_raw'] = raw
                    bad += 1
                    label = 'Недоступен: ' if item.get('blocked') else 'Ошибка: '
                    self.emit('row', ident, label + explain(raw), 'fail')
                    self.say(f'Ошибка: {title} — {explain(raw)}', 'err')
                processed += 1
                self.save_report(output, report)
                self.emit('progress', processed, len(items), good, bad)

            pending = []
            for item in items:
                if item.get('blocked'):
                    record(item['id'], None, item['blocked'])
                else:
                    pending.append(item)
            if pending:
                exe = self.prepare_steamcmd()
                self.emit('status', 'Подключаемся к Steam…')
                self.say(f'Скачиваю {len(pending)} из {len(items)} одной сессией. Полная проверка: {"да" if validate else "нет"}.')
                self.download_batch(exe, pending, validate, record)
            report['state'] = 'completed' if bad == 0 else 'completed_with_errors'
            self.emit('status', f'Готово: скачано {good}, с ошибками {bad}.' if bad else f'Готово! Скачано модов: {good}.')
            self.say('Моды не включены в игре автоматически — см. КАК_ИСПОЛЬЗОВАТЬ.txt в папке результата.')
        except Cancelled:
            if report:
                report['state'] = 'cancelled'
                for item in report['items']:
                    item.setdefault('status', 'not_processed')
            self.emit('status', 'Остановлено. Уже скачанные моды сохранены.')
            self.say('Остановлено пользователем.')
        except Exception as exc:
            if report:
                report['state'] = 'failed'
                for item in report['items']:
                    item.setdefault('status', 'not_processed')
                report['error'] = str(exc)
            self.emit('status', 'Не удалось завершить.')
            self.say(str(exc), 'err')
            self.say(traceback.format_exc(), 'err', raw=True)
            self.emit('error', str(exc))
        finally:
            try:
                if report and output:
                    self.save_report(output, report)
            except OSError as exc:
                self.say(f'Не удалось сохранить отчёт: {exc}', 'err')
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            self.close_log()
            self.emit('done')

    def save_report(self, output, report):
        temp = output / 'collection.json.tmp'
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(output / 'collection.json')
        apps = report.get('games', {})
        (output / 'КАК_ИСПОЛЬЗОВАТЬ.txt').write_text(howto_text(list(apps.values()), set(apps)), encoding='utf-8-sig')

    # ---------- обновление окна ----------
    def drain(self):
        # Ограниченная порция за тик — окно не зависает при большом потоке событий.
        for _ in range(150):
            try:
                kind, values = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                stamp, text, tag = values
                self.log.configure(state='normal')
                self.log.insert('end', f'{stamp}  {text}\n', {'err': 'err', 'good': 'good'}.get(tag, ''))
                if int(self.log.index('end-1c').split('.')[0]) > 1500:
                    self.log.delete('1.0', '300.0')
                self.log.see('end')
                self.log.configure(state='disabled')
            elif kind == 'status':
                self.status.set(values[0])
            elif kind == 'info':
                self.info.set(values[0])
            elif kind == 'items':
                self.tree.delete(*self.tree.get_children())
                self.rows = {}
                for ident, title, size, status, tag in values[0]:
                    self.rows[ident] = (title, ident, size)
                    self.tree.insert('', 'end', iid=ident, values=(title, ident, size, status), tags=(tag,))
            elif kind == 'row':
                ident, status, tag = values
                if ident in self.rows and self.tree.exists(ident):
                    title, _, size = self.rows[ident]
                    self.tree.item(ident, values=(title, ident, size, status), tags=(tag,))
                    if tag == 'busy':
                        self.tree.see(ident)
            elif kind == 'progress':
                done, total, good, bad = values
                self.progress.configure(maximum=max(total, 1), value=done)
                self.counter.set(f'Обработано {done} из {total}   •   скачано {good}   •   ошибок {bad}')
            elif kind == 'error':
                messagebox.showerror('Загрузка прервана', values[0])
            elif kind == 'done':
                self.running = False
                self.set_busy(False)
        self.after(100, self.drain)

    def close(self):
        if self.running:
            if messagebox.askyesno('Идёт работа', 'Остановить? Уже скачанные файлы останутся. После остановки окно можно закрыть.'):
                self.stop()
            return
        self.destroy()


if __name__ == '__main__':
    if os.name != 'nt':
        raise SystemExit('Эта версия предназначена для Windows 10/11.')
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().mainloop()
