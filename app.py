"""CSV Import Studio v5 — Space Edition (Tkinter desktop UI).

Large read-only CSV preview with zoom/pop-out, one-click target-column renaming,
inline Data Type controls and the unchanged, tested MySQL import engine.
"""
from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from importer_core import (
    CSVSpec, ColumnMapping, DbSettings, ImportOptions, FilePreview,
    DELIMITERS, ENCODINGS, TYPES, INDEXABLE_TYPES,
    connect, list_schemas, list_tables, list_columns,
    preview_csv, count_csv_rows, run_import, unique_key_columns,
    validate_simple_identifier, quote_identifier,
)

# Mission-control palette. No external UI framework or fonts are required.
FONT = 'Segoe UI' if sys.platform == 'win32' else 'Noto Sans Thai'
BG = '#080E24'              # deep-space application backdrop
WHITE = '#121C3A'           # panel surface (historical constant name)
INPUT_BG = '#1B2950'
INK = '#F2F5FF'             # primary text
MUTED = '#B0BDE0'
FAINT = '#8594B8'
BORDER = '#354477'
PRIMARY = '#925DFF'         # neon-violet call to action
PRIMARY_DARK = '#CCB7FF'    # readable lilac on dark backgrounds
PALE = '#272150'
HIGHLIGHT = '#382D78'
NAVY = '#090D27'
NAVY_2 = '#222651'
GREEN = '#66E8C1'
GREEN_PALE = '#103A41'
RED = '#FF99B2'
RED_PALE = '#3A1D35'
STRIPE = '#19254A'
CYAN = '#6EDAFB'
HEADING_BG = '#253461'

MODE_LABELS = {
    'สร้างตารางใหม่ (Create)': 'create',
    'เพิ่มข้อมูลต่อท้าย (Append)': 'append',
    'เพิ่ม / อัปเดตตาม Key (Upsert)': 'upsert',
    'แทนที่ข้อมูลทั้งหมด (Replace)': 'replace',
}
MODE_DISPLAY = {'create': 'Create', 'append': 'Append',
                'upsert': 'Upsert', 'replace': 'Replace'}


def label(parent, text='', *, color=INK, size=10, bold=False,
          bg=WHITE, **kwargs):
    return tk.Label(parent, text=text, bg=bg, fg=color,
                    font=(FONT, size, 'bold' if bold else 'normal'),
                    anchor=kwargs.pop('anchor', 'w'), **kwargs)


def make_button(parent, title, command, *, kind='soft', padx=16, pady=9):
    options = {
        'primary': (PRIMARY, '#FFFFFF', '#AD83FF', '#FFFFFF'),
        'soft': (PALE, '#E4D9FF', '#413273', '#FFFFFF'),
        'white': (WHITE, INK, '#24345D', INK),
        'dark': (NAVY_2, INK, '#303A71', INK),
    }
    bg, fg, active_bg, active_fg = options[kind]
    btn = tk.Button(
        parent, text=title, command=command, cursor='hand2',
        bg=bg, fg=fg, activebackground=active_bg,
        activeforeground=active_fg, font=(FONT, 10, 'bold'),
        relief='flat', bd=0, padx=padx, pady=pady,
        highlightthickness=1,
        highlightbackground=(BORDER if kind == 'white' else bg),
        highlightcolor=CYAN, disabledforeground=FAINT,
        takefocus=True,
    )
    def hover(on):
        if str(btn.cget('state')) == 'normal':
            btn.configure(bg=active_bg if on else bg,
                highlightbackground=active_bg if on else (BORDER if kind == 'white' else bg))
    btn.bind('<Enter>', lambda _e: hover(True), add='+')
    btn.bind('<Leave>', lambda _e: hover(False), add='+')
    return btn


def make_entry(parent, variable, *, show=None):
    return tk.Entry(parent, textvariable=variable, show=show or '',
                    font=(FONT, 10), bg=INPUT_BG, fg=INK,
                    insertbackground=CYAN, relief='flat', bd=0,
                    highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=PRIMARY,
                    selectbackground=HIGHLIGHT, selectforeground=INK)


def set_theme(root):
    root.option_add('*Font', (FONT, 10))
    style = ttk.Style(root)
    style.theme_use('clam')
    for name, pad in [('Studio.TCombobox',(10, 9)),('Cell.TCombobox',(7, 4))]:
        style.configure(name, padding=pad, borderwidth=1,
                        foreground=INK, fieldbackground=INPUT_BG,
                        background=INPUT_BG, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER,
                        arrowcolor=PRIMARY_DARK, arrowsize=15)
        style.map(name, fieldbackground=[('readonly', INPUT_BG), ('disabled', '#151C35')],
                  foreground=[('readonly', INK), ('disabled', FAINT)],
                  background=[('readonly', INPUT_BG), ('active', '#293567')],
                  bordercolor=[('focus', PRIMARY),('hover', CYAN)])
    style.configure('Studio.Treeview', font=(FONT, 10), rowheight=38,
                    background=WHITE, fieldbackground=WHITE, foreground=INK,
                    borderwidth=0, relief='flat')
    style.map('Studio.Treeview', background=[('selected', HIGHLIGHT)],
              foreground=[('selected', '#FFFFFF')])
    style.configure('Studio.Treeview.Heading', font=(FONT, 10, 'bold'),
                    background=HEADING_BG, foreground='#E2E9FF',
                    relief='flat', borderwidth=0, padding=(14, 10))
    style.map('Studio.Treeview.Heading', background=[('active', '#3C4B8B')],
              foreground=[('active', '#FFFFFF')])
    style.configure('Preview.Treeview', font=(FONT, 11), rowheight=39,
                    background=WHITE, fieldbackground=WHITE, foreground=INK,
                    borderwidth=0, relief='flat')
    style.map('Preview.Treeview', background=[('selected', HIGHLIGHT)],
              foreground=[('selected', '#FFFFFF')])
    style.configure('Preview.Treeview.Heading', font=(FONT, 10, 'bold'),
                    background=HEADING_BG, foreground='#E2E9FF',
                    relief='flat', borderwidth=0, padding=(14, 12))
    style.map('Preview.Treeview.Heading', background=[('active', '#3C4B8B')])
    style.configure('Studio.Horizontal.TProgressbar', troughcolor='#222D52',
                    background=PRIMARY, bordercolor='#222D52', thickness=9)
    for orientation in ('Vertical','Horizontal'):
        style.configure(f'Studio.{orientation}.TScrollbar',
                        background='#43518A', troughcolor=BG,
                        arrowcolor=CYAN, bordercolor=BG,
                        lightcolor=BG, darkcolor=BG)


def card(parent):
    return tk.Frame(parent, bg=WHITE, highlightbackground=BORDER,
                    highlightthickness=1, bd=0)


def section(parent, number: str, heading: str, sub: str = ''):
    outer = card(parent)
    head = tk.Frame(outer, bg=WHITE)
    head.pack(fill='x', padx=17, pady=(16, 7))
    num = tk.Label(head, text=number, bg=PALE, fg=CYAN,
                   font=(FONT, 11, 'bold'), padx=11, pady=8)
    num.pack(side='left', padx=(0, 11))
    header_text = tk.Frame(head, bg=WHITE)
    header_text.pack(side='left', fill='x', expand=True)
    label(header_text, heading, size=11, bold=True).pack(anchor='w')
    if sub:
        label(header_text, sub, size=9, color=MUTED).pack(anchor='w', pady=(2, 0))
    body = tk.Frame(outer, bg=WHITE)
    body.pack(fill='x', padx=17, pady=(7, 17))
    return outer, body

class ImportStudio(tk.Tk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.title('CSV Import Studio v5  |  Space Edition')
        self.minsize(1030, 670)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(1620, max(1030, screen_width - 36))
        height = min(1000, max(670, screen_height - 45))
        self.geometry(f'{width}x{height}')
        self.compact_layout = screen_height < 850
        if self.compact_layout:
            ttk.Style(self).configure('Studio.Treeview', rowheight=36)
        self.configure(bg=BG)
        set_theme(self)

        self.bus = queue.Queue()
        self.cancel_flag = threading.Event()
        self.is_importing = False
        self.preview: FilePreview | None = None
        self.row_count: int | None = None
        self.blank_row_count: int | None = None
        self._rowcount_token = 0
        self._last_suggested_table = ''
        self.mappings: list[ColumnMapping] = []
        self.schemas: list[str] = []
        self.tables: list[str] = []
        self.table_columns: list[dict] = []
        self.unique_keys: list[str] = []
        self.unique_index_count = 0
        self.connected = False
        self.demo = demo
        self._schema_after = None
        self._table_after = None
        self._active_editor = None
        self._active_editor_item = None
        self.preview_popup = None
        self.preview_font_size = 11
        self._space_images = []
        self._asset_folder = Path(__file__).parent / 'assets'
        try:
            icon = tk.PhotoImage(file=str(self._asset_folder / 'app_icon.png'))
            self.iconphoto(True, icon)
            self._space_images.append(icon)
        except tk.TclError:
            pass

        self.host_var = tk.StringVar(value='127.0.0.1')
        self.port_var = tk.StringVar(value='3306')
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        self.csv_path_var = tk.StringVar()
        self.encoding_var = tk.StringVar(value='Auto')
        self.delimiter_var = tk.StringVar(value='Auto')
        self.schema_var = tk.StringVar()
        self.create_schema_var = tk.BooleanVar(value=False)
        self.table_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=next(iter(MODE_LABELS)))
        self.key_var = tk.StringVar()
        self.file_name_var = tk.StringVar(value='ยังไม่ได้เลือกไฟล์')
        self.file_meta_var = tk.StringVar(value='เลือก CSV เพื่อเริ่มต้น')
        self.destination_var = tk.StringVar(value='ปลายทาง: ยังไม่ได้ระบุ Schema / Table')
        self.stat_columns_var = tk.StringVar(value='—')
        self.stat_rows_var = tk.StringVar(value='—')
        self.status_var = tk.StringVar(value='พร้อมเริ่มต้น • กรุณาเลือกไฟล์ CSV')
        self.mapping_count_var = tk.StringVar(value='0 คอลัมน์')
        self.progress_var = tk.IntVar(value=0)

        self._build_ui()
        self.after(120, self._drain_bus)
        self.schema_var.trace_add('write', lambda *_: (self._schedule_schema_fetch(), self._refresh_destination()))
        self.table_var.trace_add('write', lambda *_: (self._schedule_table_fetch(), self._refresh_destination()))
        self.create_schema_var.trace_add('write', lambda *_: self._refresh_destination())
        self.mode_var.trace_add('write', lambda *_: self._refresh_destination())
        if demo:
            self.after(240, self._load_demo)

    def _build_ui(self):
        # Luminous space masthead; all images are local PNGs and Tk-native.
        bar = tk.Frame(self, bg=NAVY, height=(74 if self.compact_layout else 90))
        bar.pack(fill='x')
        bar.pack_propagate(False)
        bg_path = self._asset_folder / 'space_header.png'
        if bg_path.exists():
            try:
                bg_img = tk.PhotoImage(file=str(bg_path))
                self._space_images.append(bg_img)
                art = tk.Label(bar, image=bg_img, bd=0, bg=NAVY)
                art.place(relx=1, y=0, anchor='ne')
                art.lower()
            except tk.TclError:
                pass
        orbit_logo = tk.Canvas(bar, bg=NAVY, width=56, height=52,
                               highlightthickness=0)
        orbit_logo.pack(side='left', padx=(23, 11), pady=9)
        orbit_logo.create_oval(8, 8, 45, 45, fill='#302476', outline=PRIMARY, width=3)
        orbit_logo.create_oval(0, 21, 52, 32, outline=CYAN, width=2)
        orbit_logo.create_rectangle(21, 17, 35, 22, fill='#D8C6FF', outline='')
        orbit_logo.create_rectangle(21, 25, 35, 30, fill=PRIMARY, outline='')
        orbit_logo.create_rectangle(21, 33, 35, 38, fill=CYAN, outline='')
        name = tk.Frame(bar, bg=NAVY)
        name.pack(side='left', pady=(11 if self.compact_layout else 16))
        label(name, 'CSV Import Studio', size=(17 if self.compact_layout else 19),
              bold=True, color=INK, bg=NAVY).pack(anchor='w')
        label(name, 'O R B I T A L   D A T A   W O R K S P A C E',
              size=8, color=CYAN, bg=NAVY).pack(anchor='w', pady=(2,0))
        self.connected_label = tk.Label(bar, text='●  MySQL / ยังไม่เชื่อมต่อ',
            bg=NAVY_2, fg='#CFD9FF', font=(FONT, 9, 'bold'), padx=15, pady=8)
        self.connected_label.pack(side='right', padx=(8, 23))
        label(bar, 'LOCAL / SECURE', size=9, color='#B6AEDE', bg=NAVY).pack(
            side='right', padx=(0, 3))
        tk.Frame(self, bg=PRIMARY, height=2).pack(fill='x')

        shell = tk.Frame(self, bg=BG)
        shell.pack(fill='both', expand=True, padx=(14 if self.compact_layout else 19),
                   pady=(10 if self.compact_layout else 13))
        shell.grid_columnconfigure(0, minsize=(310 if self.compact_layout else 337), weight=0)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)
        left = tk.Frame(shell, bg=BG, width=(310 if self.compact_layout else 337))
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        left.pack_propagate(False)
        self._build_sidebar(left)
        right = tk.Frame(shell, bg=BG)
        right.grid(row=0, column=1, sticky='nsew')
        self._build_workspace(right)
        foot = tk.Frame(self, bg=BG, height=20)
        foot.pack(fill='x')
        foot.pack_propagate(False)
        label(foot, 'SOURCE  CSV    →    TARGET  MySQL    /    ค่าข้อมูลต้นฉบับไม่ถูกแก้ไข',
              color=MUTED, size=8, bg=BG).pack(side='left', padx=19)
        label(foot, 'SPACE EDITION  •  v5', color=FAINT, size=8, bg=BG).pack(side='right', padx=18)

    def _build_sidebar(self, parent):
        header = tk.Frame(parent, bg=BG)
        header.pack(fill='x', pady=(1, 9))
        label(header, 'MISSION SETUP', size=13, bold=True, bg=BG).pack(side='left')
        make_button(header, 'ตั้งค่า MySQL  ↓', lambda: canvas.yview_moveto(1),
                    kind='soft', padx=12, pady=5).pack(side='right')
        # Illustrated step rail is decorative: all functional controls remain below.
        side = tk.Canvas(parent, height=(56 if self.compact_layout else 73),
                         bg=NAVY, highlightbackground=BORDER, highlightthickness=1)
        side.pack(fill='x', pady=(0, 10))
        try:
            pic = tk.PhotoImage(file=str(self._asset_folder / 'space_sidebar.png'))
            self._space_images.append(pic)
            side.create_image(0, 0, image=pic, anchor='nw')
        except tk.TclError:
            pass
        side.create_text(16, 22, anchor='w', text='CSV  →  MYSQL',
                         fill='#F4EEFF', font=(FONT, 13, 'bold'))
        side.create_text(16, 44, anchor='w', text='กำหนดเส้นทางข้อมูลของคุณ',
                         fill='#C8D2FF', font=(FONT, 9))
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill='both', expand=True)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview,
                               style='Studio.Vertical.TScrollbar')
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = tk.Frame(canvas, bg=BG)
        handle = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(handle, width=event.width))

        def wheel(event):
            if event.delta:
                canvas.yview_scroll(-int(event.delta / 120), 'units')
        def bind_wheel(_event):
            canvas.bind_all('<MouseWheel>', wheel)
        def unbind_wheel(_event):
            canvas.unbind_all('<MouseWheel>')
        canvas.bind('<Enter>', bind_wheel)
        canvas.bind('<Leave>', unbind_wheel)

        # Step 1 - Start from the user's local file.
        outer, body = section(content, '01', 'เลือกไฟล์ CSV', 'อ่านตัวอย่างและนับจำนวนแถวให้ทันที')
        outer.pack(fill='x', pady=(0, 13))
        label(body, 'ไฟล์ CSV จากเครื่อง', size=9).pack(anchor='w')
        picker = tk.Frame(body, bg=WHITE)
        picker.pack(fill='x', pady=(6, 11))
        picker.grid_columnconfigure(0, weight=1)
        pentry = make_entry(picker, self.csv_path_var)
        pentry.grid(row=0, column=0, sticky='ew', ipady=8, padx=(0, 6))
        make_button(picker, 'เลือกไฟล์', self._select_file, kind='soft', padx=11).grid(row=0, column=1, sticky='nsew')
        formats = tk.Frame(body, bg=WHITE)
        formats.pack(fill='x')
        formats.grid_columnconfigure(0, weight=1)
        formats.grid_columnconfigure(1, weight=1)
        label(formats, 'Encoding', size=9).grid(row=0, column=0, sticky='w')
        label(formats, 'ตัวคั่นข้อมูล', size=9).grid(row=0, column=1, sticky='w', padx=(9, 0))
        self.encoding_combo = ttk.Combobox(formats, textvariable=self.encoding_var,
                                            values=list(ENCODINGS), state='readonly', style='Studio.TCombobox')
        self.encoding_combo.grid(row=1, column=0, sticky='ew', pady=(5, 8))
        self.delimiter_combo = ttk.Combobox(formats, textvariable=self.delimiter_var,
                                             values=list(DELIMITERS), state='readonly', style='Studio.TCombobox')
        self.delimiter_combo.grid(row=1, column=1, sticky='ew', padx=(9, 0), pady=(5, 8))
        make_button(body, '↻   อ่าน CSV ใหม่', self._load_preview, kind='white', padx=8, pady=6).pack(anchor='w')

        # Step 2 - Prominent, editable destination names; no SQL required.
        outer, body = section(content, '02', 'ตั้งชื่อ Schema และ Table', 'พิมพ์ชื่อใหม่ หรือเลือกชื่อเดิมจากรายการ')
        outer.pack(fill='x', pady=(0, 13))
        label(body, 'Schema / Database', size=9, bold=True).pack(anchor='w')
        self.schema_combo = ttk.Combobox(body, textvariable=self.schema_var, style='Studio.TCombobox')
        self.schema_combo.pack(fill='x', pady=(5, 5))
        label(body, 'ตัวอย่าง: sales_db หรือ label_idcard_mobile', size=8, color=MUTED).pack(anchor='w')
        tk.Checkbutton(body, text='สร้าง Schema ใหม่ (หากยังไม่มีใน MySQL)', bg=WHITE, fg=INK,
                       variable=self.create_schema_var, command=self._schema_mode_changed,
                       selectcolor=INPUT_BG, activebackground=WHITE, activeforeground=INK, cursor='hand2',
                       font=(FONT, 9)).pack(anchor='w', pady=(7, 11))
        label(body, 'Table / ชื่อตารางปลายทาง', size=9, bold=True).pack(anchor='w')
        self.table_combo = ttk.Combobox(body, textvariable=self.table_var, style='Studio.TCombobox')
        self.table_combo.pack(fill='x', pady=(5, 5))
        label(body, 'แก้ชื่อที่แนะนำจากชื่อไฟล์ได้เลย', size=8, color=MUTED).pack(anchor='w', pady=(0, 10))
        label(body, 'วิธีการนำเข้า', size=9).pack(anchor='w')
        self.mode_combo = ttk.Combobox(body, textvariable=self.mode_var, values=list(MODE_LABELS),
                                       state='readonly', style='Studio.TCombobox')
        self.mode_combo.pack(fill='x', pady=(5, 11))
        self.mode_combo.bind('<<ComboboxSelected>>', lambda _: self._mode_changed())
        label(body, 'Unique Key (ถ้าต้องการ)', size=9).pack(anchor='w')
        self.key_combo = ttk.Combobox(body, textvariable=self.key_var,
                                      state='readonly', style='Studio.TCombobox')
        self.key_combo.pack(fill='x', pady=(5, 6))
        self.key_combo.bind('<<ComboboxSelected>>', lambda _: self._update_tip())
        self.key_tip = label(body, 'Create: เลือกได้ หรือเว้นว่างถ้าไม่ต้องการ Key',
                             size=9, color=MUTED, wraplength=318, justify='left')
        self.key_tip.pack(fill='x', pady=(3, 0))
        self._refresh_key_options()

        # Step 3 - Connection test, while file + destination are accessible first.
        outer, body = section(content, '03', 'เชื่อมต่อ MySQL', 'ใช้บัญชีที่มีสิทธิ์กับ Schema / Table ปลายทาง')
        outer.pack(fill='x', pady=(0, 13))
        pair = tk.Frame(body, bg=WHITE)
        pair.pack(fill='x')
        pair.grid_columnconfigure(0, weight=3)
        pair.grid_columnconfigure(1, weight=1)
        label(pair, 'Host / IP', size=9).grid(row=0, column=0, sticky='w')
        label(pair, 'Port', size=9).grid(row=0, column=1, sticky='w', padx=(9, 0))
        make_entry(pair, self.host_var).grid(row=1, column=0, sticky='ew', ipady=8, pady=(5, 9))
        make_entry(pair, self.port_var).grid(row=1, column=1, sticky='ew', ipady=8, padx=(9, 0), pady=(5, 9))
        label(body, 'Username', size=9).pack(anchor='w')
        make_entry(body, self.user_var).pack(fill='x', ipady=8, pady=(5, 9))
        label(body, 'Password', size=9).pack(anchor='w')
        make_entry(body, self.pass_var, show='●').pack(fill='x', ipady=8, pady=(5, 11))
        make_button(body, 'ทดสอบการเชื่อมต่อ', self._test_connection, kind='soft').pack(fill='x')
        make_button(body, '↑  กลับไปเลือกไฟล์', lambda: canvas.yview_moveto(0),
                    kind='white', padx=9, pady=6).pack(anchor='w', pady=(7, 0))

    def _build_workspace(self, right):
        for row, weight in enumerate((0, 0, 0, 0, 1, 0)):
            right.grid_rowconfigure(row, weight=weight)
        right.grid_columnconfigure(0, weight=1)

        intro = tk.Frame(right, bg=BG)
        intro.grid(row=0, column=0, sticky='ew', pady=(0, 7))
        heading = tk.Frame(intro, bg=BG)
        heading.pack(side='left', fill='x', expand=True)
        label(heading, 'MISSION CONTROL    /    DATA INGESTION',
              color=CYAN, size=8, bold=True, bg=BG).pack(anchor='w', pady=(0, 2))
        label(heading, 'นำเข้าข้อมูล CSV', size=(18 if self.compact_layout else 20),
              bold=True, bg=BG).pack(anchor='w')
        # Keep the preview tall; the workflow description is in the left step rail.
        route = tk.Canvas(intro, bg=BG, highlightthickness=0, width=166, height=52)
        route.pack(side='right', padx=(7, 0))
        route.create_oval(4, 8, 45, 46, fill='#241C58', outline=PRIMARY, width=2)
        route.create_text(25, 27, text='CSV', font=(FONT, 9, 'bold'), fill=INK)
        route.create_line(48, 27, 117, 27, dash=(4, 4), arrow=tk.LAST,
                          fill=CYAN, width=2)
        route.create_rectangle(122, 8, 163, 46, fill='#243D65', outline=CYAN, width=2)
        route.create_text(142, 27, text='SQL', fill=INK, font=(FONT, 9, 'bold'))

        stats = tk.Frame(right, bg=BG)
        stats.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        stats.grid_columnconfigure(0, weight=5)
        stats.grid_columnconfigure(1, weight=2)
        stats.grid_columnconfigure(2, weight=2)
        def metric(col, kicker, valvar, highlight=False):
            box = card(stats)
            box.grid(row=0, column=col, sticky='nsew', padx=(8 if col else 0, 0))
            label(box, kicker.upper() if col else kicker, color=MUTED,
                  size=8, bold=True).pack(anchor='w', padx=15, pady=(4, 0))
            lab = label(box, '', textvariable=valvar, size=(12 if col == 0 else 17),
                        color=(CYAN if highlight else INK), bold=True,
                        wraplength=(350 if col == 0 else 115))
            lab.pack(anchor='w', padx=15, pady=(0, 3))
        metric(0, 'ไฟล์ที่เลือก', self.file_name_var)
        metric(1, 'แถวทั้งหมด', self.stat_rows_var, True)
        metric(2, 'คอลัมน์', self.stat_columns_var)

        destination_strip = card(right)
        destination_strip.grid(row=2, column=0, sticky='ew', pady=(0, 8))
        tk.Frame(destination_strip, bg=CYAN, width=3).pack(side='left', fill='y')
        label(destination_strip, 'TARGET', size=8, bold=True, color=CYAN).pack(
            side='left', padx=(12, 9), pady=7)
        label(destination_strip, '', textvariable=self.destination_var,
              color=PRIMARY_DARK, size=9, bold=True).pack(side='left', pady=4)

        tabs = tk.Frame(right, bg=BG)
        tabs.grid(row=3, column=0, sticky='ew', pady=(0, 7))
        self.preview_tab_btn = tk.Button(tabs, text='  ◈  Preview CSV  ',
            font=(FONT, 10, 'bold'), padx=12, pady=6,
            bg=PALE, fg=INK, relief='flat', bd=0, cursor='hand2',
            command=lambda: self._switch_tab('preview'))
        self.preview_tab_btn.pack(side='left', padx=(0, 7))
        self.mapping_tab_btn = tk.Button(tabs, text='  ✎  Column Mapping  ',
            font=(FONT, 10, 'bold'), padx=12, pady=6,
            bg=WHITE, fg=MUTED, relief='flat', bd=0, cursor='hand2',
            command=lambda: self._switch_tab('mapping'))
        self.mapping_tab_btn.pack(side='left')
        label(tabs, 'READ-ONLY SOURCE  /  EDITABLE TARGET', size=8,
              color=FAINT, bg=BG).pack(side='right', pady=6)

        top = card(right)
        top.grid(row=4, column=0, sticky='nsew', pady=(0, 8))
        self.preview_card = top
        top.grid_columnconfigure(0, weight=1)
        top.grid_rowconfigure(1, weight=1)
        preview_h = tk.Frame(top, bg=WHITE)
        preview_h.grid(row=0, column=0, sticky='ew', padx=14, pady=(8, 6))
        label(preview_h, 'DATA PREVIEW', size=11, bold=True).pack(side='left', padx=(0, 12))
        label(preview_h, '20 RECORDS', size=8, bold=True, color=CYAN,
              bg=PALE, padx=9, pady=4).pack(side='left')
        self.expand_btn = make_button(preview_h, '↗  ขยายตัวอย่าง', self._open_large_preview,
                                      kind='soft', padx=9, pady=4)
        self.expand_btn.pack(side='right', padx=(6, 0))
        self.rename_from_preview_btn = make_button(
            preview_h, '✎  แก้ชื่อคอลัมน์', self._jump_to_column_names,
            kind='white', padx=9, pady=4)
        self.rename_from_preview_btn.pack(side='right', padx=(6, 0))
        make_button(preview_h, 'A+', lambda: self._change_preview_zoom(1),
                    kind='white', padx=7, pady=4).pack(side='right', padx=(2, 0))
        make_button(preview_h, 'A−', lambda: self._change_preview_zoom(-1),
                    kind='white', padx=7, pady=4).pack(side='right', padx=(7, 0))
        preview_wrap = tk.Frame(top, bg=WHITE)
        preview_wrap.grid(row=1, column=0, sticky='nsew', padx=12, pady=(0, 4))
        preview_wrap.grid_columnconfigure(0, weight=1)
        preview_wrap.grid_rowconfigure(0, weight=1)
        self.preview_tree = ttk.Treeview(preview_wrap, columns=(), show='headings',
                                        style='Preview.Treeview', selectmode='browse')
        preview_y = ttk.Scrollbar(preview_wrap, orient='vertical',
                                   command=self.preview_tree.yview,
                                   style='Studio.Vertical.TScrollbar')
        preview_x = ttk.Scrollbar(preview_wrap, orient='horizontal',
                                   command=self.preview_tree.xview,
                                   style='Studio.Horizontal.TScrollbar')
        self.preview_tree.configure(xscrollcommand=preview_x.set, yscrollcommand=preview_y.set)
        self.preview_tree.grid(row=0, column=0, sticky='nsew')
        preview_y.grid(row=0, column=1, sticky='ns')
        preview_x.grid(row=1, column=0, sticky='ew')
        self.preview_tree.tag_configure('stripe', background=STRIPE)
        self.preview_tree.tag_configure('empty', foreground=FAINT)
        self.preview_tree.bind('<Double-Button-1>', self._preview_header_double_click)
        self.file_detail_var = tk.StringVar(value='เลือกไฟล์ CSV เพื่อแสดงตัวอย่าง 20 แถวแรก')
        label(top, '', textvariable=self.file_detail_var, size=9,
              color=MUTED).grid(row=2, column=0, sticky='ew', padx=14, pady=(0, 7))

        bottom = card(right)
        bottom.grid(row=4, column=0, sticky='nsew', pady=(0, 8))
        self.mapping_card = bottom
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_rowconfigure(1, weight=1)
        mapping_header = tk.Frame(bottom, bg=WHITE)
        mapping_header.grid(row=0, column=0, sticky='ew', padx=15, pady=(10, 7))
        textblock = tk.Frame(mapping_header, bg=WHITE)
        textblock.pack(side='left')
        label(textblock, 'COLUMN MAPPING', size=11, bold=True).pack(anchor='w')
        label(textblock, 'คลิกชื่อคอลัมน์ปลายทางแล้วพิมพ์ได้ทันที  •  Enter เพื่อบันทึก',
              size=9, color=MUTED).pack(anchor='w', pady=(2, 0))
        self.all_text_btn = make_button(mapping_header, 'ตั้งทุกคอลัมน์เป็น TEXT',
                                        self._set_all_text, kind='soft', padx=10, pady=6)
        self.all_text_btn.pack(side='right')
        map_area = tk.Frame(bottom, bg=WHITE)
        map_area.grid(row=1, column=0, sticky='nsew', padx=12)
        map_area.grid_columnconfigure(0, weight=1)
        map_area.grid_rowconfigure(0, weight=1)
        self.mapping_tree = ttk.Treeview(map_area,
            columns=('seq', 'source', 'target', 'dtype', 'enabled'),
            show='headings', style='Studio.Treeview', selectmode='browse')
        for col_id, heading, width, minw, anchor in (
            ('seq', '#', 44, 36, 'center'),
            ('source', 'ชื่อใน CSV (ต้นฉบับ)', 206, 133, 'w'),
            ('target', '✎  ชื่อใน MySQL (คลิกแก้)', 249, 153, 'w'),
            ('dtype', 'Data Type  ▾', 170, 125, 'w'),
            ('enabled', 'นำเข้า', 64, 60, 'center'),
        ):
            self.mapping_tree.heading(col_id, text=heading)
            self.mapping_tree.column(col_id, width=width, minwidth=minw,
                    anchor=anchor, stretch=(col_id in ('source','target','dtype')))
        map_y = ttk.Scrollbar(map_area, orient='vertical',
                              command=self._mapping_scroll,
                              style='Studio.Vertical.TScrollbar')
        map_x = ttk.Scrollbar(map_area, orient='horizontal',
                              command=self.mapping_tree.xview,
                              style='Studio.Horizontal.TScrollbar')
        self.mapping_tree.configure(yscrollcommand=map_y.set, xscrollcommand=map_x.set)
        self.mapping_tree.grid(row=0, column=0, sticky='nsew')
        map_y.grid(row=0, column=1, sticky='ns')
        map_x.grid(row=1, column=0, sticky='ew')
        self.mapping_tree.tag_configure('stripe', background=STRIPE)
        self.mapping_tree.tag_configure('excluded', foreground=FAINT)
        self.mapping_tree.bind('<ButtonRelease-1>', self._mapping_click)
        self.mapping_tree.bind('<Double-Button-1>', self._mapping_double_click)
        self.mapping_tree.bind('<MouseWheel>', lambda _: self._close_editor())
        map_hint = tk.Frame(bottom, bg=WHITE)
        map_hint.grid(row=2, column=0, sticky='ew', padx=14, pady=(7, 8))
        self.mapping_help_var = tk.StringVar(value='✎ คลิกชื่อปลายทางเพื่อพิมพ์  •  ▾ เลือก Data Type  •  ✓ นำเข้าคอลัมน์')
        label(map_hint, '', textvariable=self.mapping_help_var,
              size=9, color=MUTED).pack(side='left')
        label(map_hint, '', textvariable=self.mapping_count_var,
              size=9, bold=True, color=CYAN).pack(side='right')

        action = card(right)
        action.grid(row=5, column=0, sticky='ew')
        action.grid_columnconfigure(0, weight=1)
        status = tk.Frame(action, bg=WHITE)
        status.grid(row=0, column=0, sticky='ew', padx=(16, 8), pady=8)
        label(status, '', textvariable=self.status_var, size=9,
              wraplength=570, justify='left').pack(anchor='w', pady=(0, 7))
        self.progress_bar = ttk.Progressbar(status, maximum=100,
             variable=self.progress_var, style='Studio.Horizontal.TProgressbar')
        self.progress_bar.pack(fill='x')
        buttons = tk.Frame(action, bg=WHITE)
        buttons.grid(row=0, column=1, sticky='e', padx=(0, 15), pady=8)
        self.cancel_btn = make_button(buttons, 'ยกเลิก', self._cancel_import,
                                      kind='white', padx=13, pady=9)
        self.cancel_btn.configure(state='disabled')
        self.cancel_btn.pack(side='left', padx=(0, 8))
        self.run_btn = make_button(buttons, '◈  เริ่มนำเข้า  →', self._start_import,
                                   kind='primary', padx=18, pady=9)
        self.run_btn.pack(side='left')
        self._switch_tab('preview')
        self._update_tip()

    def _switch_tab(self, tab: str):
        self._close_editor()
        if tab == 'preview':
            self.mapping_card.grid_remove()
            self.preview_card.grid()
        else:
            self.preview_card.grid_remove()
            self.mapping_card.grid()
        self.preview_tab_btn.configure(
            bg=PALE if tab == 'preview' else WHITE,
            fg=CYAN if tab == 'preview' else MUTED)
        self.mapping_tab_btn.configure(
            bg=PALE if tab == 'mapping' else WHITE,
            fg=CYAN if tab == 'mapping' else MUTED)
        self.active_tab = tab

    def _refresh_destination(self):
        """Reflect user-entered Schema/Table, even before connecting to MySQL."""
        schema = self.schema_var.get().strip() or 'ยังไม่ระบุ Schema'
        table = self.table_var.get().strip() or 'ยังไม่ระบุ Table'
        mode = self.current_mode()
        suffix = '  •  สร้าง Schema ใหม่' if self.create_schema_var.get() else ''
        self.destination_var.set(f'{schema}  /  {table}    ({MODE_DISPLAY[mode]}){suffix}')

    @staticmethod
    def _suggest_table_name(path: str) -> str:
        """Offer a conventional MySQL table name from the filename, never force it."""
        stem = Path(path).stem
        suggestion = re.sub(r'[^A-Za-z0-9_]', '_', stem).strip('_')[:64]
        if not suggestion:
            return ''
        if suggestion[0].isdigit():
            suggestion = ('tbl_' + suggestion)[:64]
        return suggestion

    def _db_settings(self):
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError('Port ต้องเป็นตัวเลข 1–65535')
        if not self.host_var.get().strip() or not self.user_var.get().strip():
            raise ValueError('กรุณากรอก Host และ Username')
        return DbSettings(self.host_var.get().strip(), port,
                          self.user_var.get().strip(), self.pass_var.get())

    def _post(self, name, *args):
        self.bus.put((name, *args))

    def _test_connection(self):
        try:
            db = self._db_settings()
        except ValueError as exc:
            messagebox.showerror('การเชื่อมต่อ MySQL', str(exc))
            return
        self.status_var.set('กำลังทดสอบการเชื่อมต่อ MySQL...')
        def task():
            try:
                conn = connect(db)
                try:
                    schemas = list_schemas(conn)
                    version = conn.get_server_info()
                finally:
                    conn.close()
                self._post('connected', schemas, version)
            except Exception as exc:
                self._post('connect_error', str(exc))
        threading.Thread(target=task, daemon=True).start()

    def _schedule_schema_fetch(self):
        if self._schema_after is not None:
            self.after_cancel(self._schema_after)
        self._schema_after = self.after(350, self._fetch_tables)

    def _schedule_table_fetch(self):
        if self._table_after is not None:
            self.after_cancel(self._table_after)
        self._table_after = self.after(350, self._fetch_table_metadata)

    def _schema_mode_changed(self):
        if self.create_schema_var.get() and self.current_mode() != 'create':
            self.mode_var.set('สร้างตารางใหม่ (Create)')
            self._mode_changed()
        self._fetch_tables()

    def _fetch_tables(self):
        if not self.connected or self.create_schema_var.get():
            self.tables = []
            self.table_combo.configure(values=[])
            self.table_columns = []
            self._refresh_key_options()
            return
        schema = self.schema_var.get().strip()
        if not schema or schema not in self.schemas:
            self.tables = []
            self.table_combo.configure(values=[])
            self.table_columns = []
            self._refresh_key_options()
            return
        try:
            db = self._db_settings()
        except ValueError:
            return
        def task():
            try:
                conn = connect(db)
                try:
                    tables = list_tables(conn, schema)
                finally:
                    conn.close()
                self._post('tables', schema, tables)
            except Exception as exc:
                self._post('metadata_error', str(exc))
        threading.Thread(target=task, daemon=True).start()

    def _fetch_table_metadata(self):
        if not self.connected or self.current_mode() == 'create':
            self.table_columns = []
            self.unique_keys = []
            self.unique_index_count = 0
            self._refresh_key_options()
            return
        schema, table = self.schema_var.get().strip(), self.table_var.get().strip()
        if not schema or table not in self.tables:
            self.table_columns = []
            self.unique_keys = []
            self.unique_index_count = 0
            self._refresh_key_options()
            return
        try:
            db = self._db_settings()
        except ValueError:
            return
        def task():
            try:
                conn = connect(db)
                try:
                    columns = list_columns(conn, schema, table)
                    keys, count = unique_key_columns(conn, schema, table)
                finally:
                    conn.close()
                self._post('columns', schema, table, columns, keys, count)
            except Exception as exc:
                self._post('metadata_error', str(exc))
        threading.Thread(target=task, daemon=True).start()

    def current_mode(self):
        return MODE_LABELS.get(self.mode_var.get(), 'create')

    def _mode_changed(self):
        self._close_editor()
        mode = self.current_mode()
        if mode != 'create':
            self.create_schema_var.set(False)
        elif self.mappings:
            for m in self.mappings:
                if m.data_type not in TYPES:
                    m.data_type = 'TEXT'
                m.include = True
                m.target_name = self._safe_column(m.source_name)
        self._refresh_key_options()
        self._fetch_tables()
        self._fetch_table_metadata()
        self._refresh_mapping_table()
        self._refresh_preview_headings()
        self._update_tip()

    def _update_tip(self):
        mode = self.current_mode()
        if mode == 'create':
            self.key_tip.configure(text='Unique Key เลือกได้เฉพาะคอลัมน์ VARCHAR / ตัวเลข / วันที่')
        elif mode == 'upsert':
            self.key_tip.configure(text='Upsert ต้องเลือก Unique / Primary Key ที่มีอยู่ใน Table')
        else:
            self.key_tip.configure(text='ไม่จำเป็นต้องระบุ Unique Key สำหรับโหมดนี้')
        if hasattr(self, 'mapping_help_var'):
            if mode == 'create':
                self.mapping_help_var.set('✎ คลิกชื่อปลายทางแล้วพิมพ์  •  ▾ คลิกเลือก Data Type  •  ✓ เลือก/ยกเลิกคอลัมน์')
                self.all_text_btn.configure(state='normal')
            else:
                self.mapping_help_var.set('✎ คลิกชื่อปลายทางเพื่อจับคู่คอลัมน์  •  Data Type ตาม MySQL เดิม (เปลี่ยนไม่ได้)')
                self.all_text_btn.configure(state='disabled')

    def _refresh_key_options(self):
        if not hasattr(self, 'key_combo'):
            return
        mode = self.current_mode()
        if mode == 'create':
            keys = [''] + [m.target_name for m in self.mappings
                           if m.include and m.data_type in INDEXABLE_TYPES]
            self.key_combo.configure(values=keys, state='readonly')
            if self.key_var.get() not in keys:
                self.key_var.set('')
        elif mode == 'upsert':
            self.key_combo.configure(values=self.unique_keys, state='readonly')
            if self.key_var.get() not in self.unique_keys:
                self.key_var.set(self.unique_keys[0] if self.unique_keys else '')
        else:
            self.key_var.set('')
            self.key_combo.configure(values=[], state='disabled')

    def _select_file(self):
        filename = filedialog.askopenfilename(
            title='เลือกไฟล์ข้อมูล CSV',
            filetypes=[('CSV files', '*.csv'), ('Text files', '*.txt'), ('All files', '*.*')],
        )
        if filename:
            self.csv_path_var.set(filename)
            self._load_preview()

    def _load_preview(self):
        source = self.csv_path_var.get().strip()
        if not source:
            messagebox.showwarning('เลือกไฟล์', 'กรุณาเลือกไฟล์ CSV ก่อน')
            return
        spec = CSVSpec(source, self.encoding_var.get(), self.delimiter_var.get())
        try:
            pv = preview_csv(spec)
        except Exception as exc:
            messagebox.showerror('อ่านไฟล์ CSV ไม่สำเร็จ', str(exc))
            return
        self._close_editor()
        self._rowcount_token += 1  # Invalidate any previous count worker.
        count_token = self._rowcount_token
        self.preview = pv
        self.row_count = None
        self.blank_row_count = None
        self.mappings = [ColumnMapping(i, name, self._safe_column(name))
                         for i, name in enumerate(pv.headers)]
        self._render_preview()
        self._refresh_mapping_table()
        self._switch_tab('preview')
        if self.current_mode() != 'create' and self.table_columns:
            self._apply_existing_column_matches()
        self._refresh_key_options()

        # Table name is suggested only while still unset or auto-suggested.
        suggested = self._suggest_table_name(source)
        if suggested and (not self.table_var.get().strip() or self.table_var.get() == self._last_suggested_table):
            self.table_var.set(suggested)
            self._last_suggested_table = suggested

        self.file_name_var.set(Path(source).name)
        self.stat_columns_var.set(f'{len(pv.headers):,}')
        self.stat_rows_var.set('กำลังนับ…')
        filesize = f'{pv.file_size / (1024*1024):,.2f} MB' if pv.file_size >= 1024*1024 else f'{pv.file_size/1024:,.1f} KB'
        self.file_meta_var.set(f'{filesize} • {pv.encoding}')
        self.file_detail_var.set(
            f'{filesize}  •  Encoding: {pv.encoding}  •  ตัวคั่น: {repr(pv.delimiter)}'
            f'  •  ตัวอย่าง {len(pv.rows):,} แถว (กำลังนับแถวทั้งหมด...)'
        )
        self.status_var.set('อ่าน CSV สำเร็จ • กำลังนับจำนวนแถวข้อมูลทั้งหมด...')

        # Counting runs off the UI thread: handles multi-GB files without freezing Tk.
        def task():
            try:
                stats = count_csv_rows(
                    spec, is_cancelled=lambda: count_token != self._rowcount_token,
                )
                current = os.stat(source)
                if current.st_size != pv.file_size or current.st_mtime_ns != pv.file_mtime_ns:
                    raise ValueError('ไฟล์เปลี่ยนแปลงหลัง Preview กรุณาอ่าน CSV ใหม่')
                self._post('rowcount_done', count_token, stats.data_rows, stats.blank_rows)
            except Exception as exc:
                self._post('rowcount_error', count_token, str(exc))
        threading.Thread(target=task, daemon=True).start()

    @staticmethod
    def _safe_column(name):
        fixed = name.replace('`', '_').replace('.', '_').strip()
        return (fixed or 'column')[:64]

    def _render_preview(self):
        self._populate_preview_tree(self.preview_tree)
        if self.preview_popup is not None and self.preview_popup.winfo_exists():
            self._populate_preview_tree(self.popup_tree)

    def _refresh_preview_headings(self):
        """Show target column names in preview without changing any CSV cell/header."""
        if self.preview is None:
            return
        for idx, m in enumerate(self.mappings):
            cid = f'col_{idx}'
            if cid in self.preview_tree['columns']:
                self.preview_tree.heading(cid, text=m.target_name)
        if self.preview_popup is not None and self.preview_popup.winfo_exists():
            for idx, m in enumerate(self.mappings):
                cid = f'col_{idx}'
                if cid in self.popup_tree['columns']:
                    self.popup_tree.heading(cid, text=m.target_name)

    def _jump_to_column_names(self):
        self._switch_tab('mapping')
        if self.mappings:
            self.after(75, lambda: self._edit_target(0))

    def _change_preview_zoom(self, amount):
        self.preview_font_size = max(9, min(15, self.preview_font_size + amount))
        ttk.Style(self).configure('Preview.Treeview', font=(FONT, self.preview_font_size),
                                  rowheight=max(36, self.preview_font_size * 3 + 6))

    def _open_large_preview(self):
        """A true full-size secondary preview, never another import workflow."""
        if self.preview is None:
            messagebox.showinfo('Preview CSV', 'กรุณาเลือกไฟล์ CSV ก่อน')
            return
        if self.preview_popup is not None and self.preview_popup.winfo_exists():
            self.preview_popup.lift()
            self.preview_popup.focus_force()
            return
        win = tk.Toplevel(self)
        self.preview_popup = win
        win.title('CSV Import Studio  /  Full-Screen Data Preview')
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win.geometry(f'{min(1540,max(900,sw-75))}x{min(900,max(570,sh-95))}+25+25')
        win.minsize(730, 470)
        win.configure(bg=BG)
        if self._space_images:
            try:
                win.iconphoto(True, self._space_images[0])
            except tk.TclError:
                pass
        hdr = tk.Frame(win, bg=NAVY, height=70)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        label(hdr, '◈  FULL PREVIEW  /  ' + Path(self.csv_path_var.get()).name,
              bg=NAVY, color=INK, bold=True, size=16).pack(side='left', padx=20, pady=16)
        make_button(hdr, 'ปิดหน้าต่าง', win.destroy, kind='dark',
                    padx=11, pady=7).pack(side='right', padx=18)
        info = tk.Frame(win, bg=BG)
        info.pack(fill='x', padx=18, pady=(10, 9))
        count_text = (f'{self.row_count:,} แถว' if self.row_count is not None else 'กำลังนับแถว')
        label(info, f'CSV ทั้งหมด {count_text}  •  {len(self.preview.headers)} คอลัมน์  •  ตัวอย่าง {len(self.preview.rows)} แถวแรก',
              bg=BG, color=MUTED, size=10).pack(side='left')
        make_button(info, 'A+', lambda: self._change_preview_zoom(1),
                    kind='soft', padx=8, pady=5).pack(side='right', padx=(5,0))
        make_button(info, 'A−', lambda: self._change_preview_zoom(-1),
                    kind='white', padx=8, pady=5).pack(side='right')
        area = tk.Frame(win, bg=WHITE, highlightbackground=BORDER, highlightthickness=1)
        area.pack(fill='both', expand=True, padx=18, pady=(0, 12))
        area.grid_rowconfigure(0, weight=1)
        area.grid_columnconfigure(0, weight=1)
        self.popup_tree = ttk.Treeview(area, show='headings',
                                      style='Preview.Treeview', selectmode='browse')
        vy = ttk.Scrollbar(area, orient='vertical', command=self.popup_tree.yview,
                           style='Studio.Vertical.TScrollbar')
        vx = ttk.Scrollbar(area, orient='horizontal', command=self.popup_tree.xview,
                           style='Studio.Horizontal.TScrollbar')
        self.popup_tree.configure(yscrollcommand=vy.set, xscrollcommand=vx.set)
        self.popup_tree.grid(row=0, column=0, sticky='nsew')
        vy.grid(row=0, column=1, sticky='ns')
        vx.grid(row=1, column=0, sticky='ew')
        self.popup_tree.tag_configure('stripe', background=STRIPE)
        self._populate_preview_tree(self.popup_tree)
        label(win, 'หัวตารางแสดงชื่อคอลัมน์ปลายทาง • ไม่แก้ไขค่าในไฟล์ CSV',
              bg=BG, color=MUTED, size=9).pack(anchor='w', padx=19, pady=(0, 12))
        win.bind('<Escape>', lambda _e: win.destroy())
        win.protocol('WM_DELETE_WINDOW', win.destroy)

    def _populate_preview_tree(self, tree):
        tree.delete(*tree.get_children())
        if self.preview is None:
            tree.configure(columns=())
            return
        cols = [f'col_{i}' for i in range(len(self.preview.headers))]
        tree.configure(columns=cols)
        for idx, cid in enumerate(cols):
            hdr = self.mappings[idx].target_name if idx < len(self.mappings) else self.preview.headers[idx]
            tree.heading(cid, text=hdr)
            tree.column(cid, width=max(170,min(310,len(hdr)*10+90)),
                        minwidth=120, stretch=False, anchor='w')
        for idx, row in enumerate(self.preview.rows):
            tree.insert('', 'end', values=row,
                        tags=('stripe',) if idx % 2 else ())

    def _preview_header_double_click(self, event):
        if self.is_importing or self.preview is None:
            return
        if self.preview_tree.identify_region(event.x, event.y) != 'heading':
            return
        col = self.preview_tree.identify_column(event.x)
        try:
            idx = int(col[1:]) - 1
        except (ValueError, IndexError):
            return
        if 0 <= idx < len(self.mappings):
            self._switch_tab('mapping')
            self.mapping_tree.see(str(idx))
            self.after(70, lambda: self._edit_target(idx))

    def _mapping_scroll(self, *args):
        self._close_editor()
        self.mapping_tree.yview(*args)

    def _refresh_mapping_table(self, preserve=None):
        self._close_editor()
        selected = preserve
        if selected is None:
            old = self.mapping_tree.selection()
            selected = old[0] if old else None
        self.mapping_tree.delete(*self.mapping_tree.get_children())
        for idx, m in enumerate(self.mappings):
            type_label = m.data_type + ('    ▾' if self.current_mode() == 'create' else '')
            self.mapping_tree.insert('', 'end', iid=str(idx), values=(
                f'{idx+1:02d}', m.source_name, m.target_name,
                type_label, '✓' if m.include else '—',
            ), tags=(('excluded',) if not m.include else ('stripe',) if idx % 2 else ()))
        if selected is not None and self.mapping_tree.exists(selected):
            self.mapping_tree.selection_set(selected)
        self.mapping_count_var.set(f'{sum(m.include for m in self.mappings)} / {len(self.mappings)} คอลัมน์')

    def _mapping_click(self, event):
        if self.is_importing:
            return
        zone = self.mapping_tree.identify_region(event.x, event.y)
        if zone != 'cell':
            return
        row = self.mapping_tree.identify_row(event.y)
        col = self.mapping_tree.identify_column(event.x)
        if not row:
            return
        idx = int(row)
        if col == '#3':
            self._edit_target(idx)
        elif col == '#4' and self.current_mode() == 'create':
            self._edit_data_type(idx)
        elif col == '#5':
            self._close_editor()
            self.mappings[idx].include = not self.mappings[idx].include
            self._refresh_mapping_table(preserve=row)
            self._refresh_key_options()

    def _mapping_double_click(self, event):
        if self.is_importing:
            return
        if self.mapping_tree.identify_region(event.x, event.y) != 'cell':
            return
        row = self.mapping_tree.identify_row(event.y)
        col = self.mapping_tree.identify_column(event.x)
        if row and col == '#3':
            self._edit_target(int(row))

    def _close_editor(self):
        if self._active_editor is not None:
            widget = self._active_editor
            self._active_editor = None
            self._active_editor_item = None
            try:
                widget.destroy()
            except tk.TclError:
                pass

    def _edit_data_type(self, idx: int, *, post_dropdown=True):
        self._close_editor()
        if idx < 0 or idx >= len(self.mappings) or self.current_mode() != 'create':
            return
        bbox = self.mapping_tree.bbox(str(idx), '#4')
        if not bbox:
            return
        x, y, width, height = bbox
        value = tk.StringVar(value=self.mappings[idx].data_type)
        editor = ttk.Combobox(self.mapping_tree, state='readonly', values=TYPES,
                              textvariable=value, style='Cell.TCombobox')
        editor.place(x=x+1, y=y+1, width=max(95, width-2), height=height-2)
        self._active_editor = editor
        self._active_editor_item = idx
        def commit(_event=None):
            if self._active_editor is not editor:
                return
            if value.get() in TYPES:
                self.mappings[idx].data_type = value.get()
            self._close_editor()
            self._refresh_mapping_table(preserve=str(idx))
            self._refresh_key_options()
        editor.bind('<<ComboboxSelected>>', commit)
        editor.bind('<Escape>', lambda _: self._close_editor())
        # The editor opens IN the Data Type cell. Posting it immediately means
        # one click is enough; no separate Save button or settings panel.
        editor.focus_set()
        if post_dropdown:
            def show_popup():
                if self._active_editor is editor:
                    try:
                        self.tk.call('ttk::combobox::Post', str(editor))
                    except tk.TclError:
                        pass
            self.after(30, show_popup)

    def _edit_target(self, idx: int):
        self._close_editor()
        bbox = self.mapping_tree.bbox(str(idx), '#3')
        if not bbox:
            return
        x, y, width, height = bbox
        value = tk.StringVar(value=self.mappings[idx].target_name)
        target = tk.Entry(self.mapping_tree, textvariable=value,
                          bg=INPUT_BG, fg=INK, insertbackground=CYAN,
                          selectbackground=HIGHLIGHT, selectforeground=INK,
                          font=(FONT, 10, 'bold'), relief='flat', bd=0,
                          highlightthickness=2, highlightbackground=PRIMARY,
                          highlightcolor=CYAN)
        target.place(x=x+1, y=y+1, width=max(100, width-2), height=height-2)
        self._active_editor = target
        self._active_editor_item = idx
        def apply(_event=None):
            if self._active_editor is not target:
                return
            name = value.get().strip()
            try:
                quote_identifier(name)
                if any(m.include and m.target_name.casefold() == name.casefold()
                       for j, m in enumerate(self.mappings) if j != idx):
                    raise ValueError('ชื่อคอลัมน์ปลายทางซ้ำกับคอลัมน์อื่น')
                if self.current_mode() != 'create' and self.table_columns:
                    lookup = {c['name'].casefold(): c['name'] for c in self.table_columns}
                    if name.casefold() not in lookup:
                        raise ValueError('ชื่อคอลัมน์นี้ไม่มีอยู่ใน Table ปลายทาง')
                    name = lookup[name.casefold()]
                self.mappings[idx].target_name = name
            except ValueError as exc:
                self._close_editor()
                messagebox.showerror('ชื่อคอลัมน์ไม่ถูกต้อง', str(exc))
                return
            self._close_editor()
            self._refresh_mapping_table(preserve=str(idx))
            self._refresh_preview_headings()
            self._refresh_key_options()
            self.status_var.set(f'กำหนดชื่อคอลัมน์ปลายทางแล้ว: {self.mappings[idx].source_name} → {name}')
        target.bind('<Return>', apply)
        target.bind('<Tab>', lambda e: (apply(), 'break')[1])
        target.bind('<FocusOut>', apply)
        target.bind('<Escape>', lambda _: self._close_editor())
        target.focus_set()
        target.select_range(0, 'end')

    def _set_all_text(self):
        if self.current_mode() != 'create':
            messagebox.showinfo('ประเภทข้อมูล', 'การนำเข้าตารางเดิมจะใช้ Data Type ตามโครงสร้าง MySQL และเปลี่ยนจากโปรแกรมไม่ได้')
            return
        self._close_editor()
        for m in self.mappings:
            m.data_type = 'TEXT'
        self._refresh_mapping_table()
        self._refresh_key_options()
        self.status_var.set('ตั้ง Data Type ของทุกคอลัมน์เป็น TEXT แล้ว (ไม่ได้เปลี่ยนค่าในไฟล์ CSV)')

    def _apply_existing_column_matches(self):
        if not self.table_columns or self.current_mode() == 'create':
            return
        lookup = {c['name'].casefold(): c for c in self.table_columns}
        used = set()
        for m in self.mappings:
            info = lookup.get(m.source_name.casefold())
            if info and info['name'].casefold() not in used:
                m.target_name = info['name']
                m.include = True
                m.data_type = info['type'].upper()
                used.add(info['name'].casefold())
            else:
                m.include = False
        self._refresh_mapping_table()
        self._refresh_preview_headings()
        self.status_var.set('จับคู่ชื่อคอลัมน์ที่ตรงกับ Table เดิมให้อัตโนมัติแล้ว')

    def _build_options(self):
        if self.preview is None:
            raise ValueError('กรุณาเลือกไฟล์และดู Preview ก่อน')
        if self.row_count == 0:
            raise ValueError('ไฟล์ CSV ไม่มีแถวข้อมูล (ไม่รวมหัวตารางและแถวว่าง)')
        schema = self.schema_var.get().strip()
        table = self.table_var.get().strip()
        validate_simple_identifier(schema, 'Schema')
        validate_simple_identifier(table, 'Table')
        mode = self.current_mode()
        if not self.connected:
            raise ValueError('กรุณาทดสอบการเชื่อมต่อ MySQL ก่อนนำเข้า')
        if mode != 'create' and (schema not in self.schemas or table not in self.tables):
            raise ValueError('กรุณาเลือก Schema และ Table ที่มีอยู่สำหรับ Append / Upsert / Replace')
        if self.create_schema_var.get() and schema in self.schemas:
            raise ValueError('Schema นี้มีอยู่แล้ว กรุณาปิดตัวเลือกสร้าง Schema ใหม่')
        if mode == 'create' and schema in self.schemas and table in self.tables:
            raise ValueError('Table นี้มีอยู่แล้ว กรุณาตั้งชื่อใหม่ หรือเลือกโหมดเพิ่ม/อัปเดต')
        if mode == 'create' and schema not in self.schemas and not self.create_schema_var.get():
            raise ValueError('ไม่พบ Schema นี้ กรุณาเลือกสร้าง Schema ใหม่ หรือเชื่อมต่ออีกครั้ง')
        if mode == 'upsert' and self.unique_index_count != 1:
            raise ValueError('Upsert รองรับ Table ที่มี UNIQUE / PRIMARY KEY แบบคอลัมน์เดียว เพียง 1 ดัชนี')
        if mode == 'create' and self.key_var.get():
            matched = [m for m in self.mappings if m.include and m.target_name == self.key_var.get()]
            if not matched or matched[0].data_type not in INDEXABLE_TYPES:
                raise ValueError('Unique Key ต้องใช้ Data Type ที่ทำ Index ได้ เช่น VARCHAR / INT / DATE')
        return ImportOptions(
            csv_spec=CSVSpec(self.csv_path_var.get().strip(), self.encoding_var.get(), self.delimiter_var.get()),
            db=self._db_settings(), schema=schema, table=table,
            mode=mode, mappings=[replace(m) for m in self.mappings],
            create_schema=self.create_schema_var.get(), unique_key=self.key_var.get(),
            expected_headers=self.preview.headers, expected_size=self.preview.file_size,
            expected_mtime_ns=self.preview.file_mtime_ns,
        )

    def _start_import(self):
        if self.is_importing:
            return
        self._close_editor()
        try:
            opts = self._build_options()
        except ValueError as exc:
            messagebox.showerror('กรุณาตรวจสอบการนำเข้า', str(exc))
            return
        ncols = sum(m.include for m in opts.mappings)
        if ncols == 0:
            messagebox.showerror('ไม่มีคอลัมน์สำหรับนำเข้า', 'กรุณาเลือกอย่างน้อยหนึ่งคอลัมน์')
            return
        destination = f'{opts.schema}.{opts.table}'
        row_description = (f'{self.row_count:,} แถว' if self.row_count is not None
                           else 'กำลังนับแถว / ยังไม่ทราบจำนวนแน่นอน')
        if opts.mode == 'replace':
            answer = simpledialog.askstring('ยืนยัน Replace All',
                f'คำเตือน: ข้อมูลเดิมทั้งหมดใน {destination} จะถูกลบ แล้วแทนที่ด้วย CSV ใหม่\n'
                f'ข้อมูลต้นทาง: {row_description}\n'
                'โปรดสำรอง Table เดิมก่อน และใช้ InnoDB เพื่อให้ Rollback ได้\n\n'
                'พิมพ์ REPLACE เพื่อยืนยัน', parent=self)
            if answer != 'REPLACE':
                return
        else:
            if not messagebox.askyesno('ยืนยันการนำเข้า',
                f'ไฟล์: {Path(opts.csv_spec.path).name}\nปลายทาง: {destination}\n'
                f'วิธี: {MODE_DISPLAY[opts.mode]}\nข้อมูล CSV: {row_description}\nคอลัมน์ที่เลือก: {ncols}\n\n'
                'ระบบจะอ่านค่าจากไฟล์ตามต้นฉบับโดยไม่แก้ไขข้อมูล\nยืนยันเริ่มนำเข้าหรือไม่?'):
                return
        self.cancel_flag.clear()
        self.is_importing = True
        self.run_btn.configure(state='disabled')
        self.cancel_btn.configure(state='normal')
        self.progress_var.set(0)
        self.status_var.set('เริ่มตรวจสอบไฟล์และปลายทาง...')
        def task():
            try:
                result = run_import(opts,
                    progress=lambda percent, rows, text: self._post('progress', percent, rows, text),
                    is_cancelled=self.cancel_flag.is_set)
                self._post('done', result)
            except Exception as exc:
                self._post('import_error', str(exc))
        threading.Thread(target=task, daemon=True).start()

    def _cancel_import(self):
        if self.is_importing:
            self.cancel_flag.set()
            self.status_var.set('กำลังยกเลิก • รอคำสั่ง SQL ปัจจุบันสิ้นสุด')

    def _drain_bus(self):
        try:
            while True:
                event, *args = self.bus.get_nowait()
                if event == 'rowcount_done':
                    token, total, blanks = args
                    if token != self._rowcount_token or self.preview is None:
                        continue
                    self.row_count = total
                    self.blank_row_count = blanks
                    self.stat_rows_var.set(f'{total:,}')
                    self.file_detail_var.set(
                        f'ทั้งหมด {total:,} แถวข้อมูล (ไม่นับ Header / แถวว่าง {blanks:,})'
                        f'  •  แสดงตัวอย่าง {len(self.preview.rows):,} แถวแรก'
                        f'  •  Encoding: {self.preview.encoding}'
                    )
                    self.status_var.set(f'อ่านไฟล์สำเร็จ • ข้อมูลทั้งหมด {total:,} แถว • เลือก Schema / Table และเริ่มนำเข้าได้')
                elif event == 'rowcount_error':
                    token, message = args
                    if token != self._rowcount_token:
                        continue
                    self.stat_rows_var.set('นับไม่ได้')
                    self.status_var.set('นับแถวไม่สำเร็จ • ' + message[:120])
                elif event == 'connected':
                    schemas, version = args
                    self.connected = True
                    self.schemas = schemas
                    self.schema_combo.configure(values=schemas)
                    self.connected_label.configure(text=f'●  MySQL เชื่อมต่อแล้ว  /  {version}',
                                                   bg=GREEN_PALE, fg=GREEN)
                    self.status_var.set(f'เชื่อมต่อสำเร็จ • พบ {len(schemas)} Schema')
                    if self.schema_var.get().strip() in schemas:
                        self._fetch_tables()
                elif event == 'connect_error':
                    self.connected = False
                    self.connected_label.configure(text='●  เชื่อมต่อไม่สำเร็จ',
                                                   bg=RED_PALE, fg=RED)
                    self.status_var.set('เชื่อมต่อไม่สำเร็จ • ตรวจสอบ Host / Port / Username / Password')
                    messagebox.showerror('เชื่อมต่อ MySQL ไม่สำเร็จ', args[0])
                elif event == 'tables':
                    schema, tables = args
                    if schema == self.schema_var.get().strip():
                        self.tables = tables
                        self.table_combo.configure(values=tables)
                        self._fetch_table_metadata()
                elif event == 'columns':
                    schema, table, columns, keys, count = args
                    if (schema == self.schema_var.get().strip() and
                            table == self.table_var.get().strip() and
                            self.current_mode() != 'create'):
                        self.table_columns = columns
                        self.unique_keys = keys
                        self.unique_index_count = count
                        self._refresh_key_options()
                        self._apply_existing_column_matches()
                elif event == 'metadata_error':
                    self.status_var.set('อ่านโครงสร้าง Table ไม่สำเร็จ: ' + args[0][:150])
                elif event == 'progress':
                    percent, rows, text = args
                    self.progress_var.set(percent)
                    self.status_var.set(text)
                elif event == 'done':
                    result = args[0]
                    self.is_importing = False
                    self.run_btn.configure(state='normal')
                    self.cancel_btn.configure(state='disabled')
                    self.progress_var.set(100)
                    self.status_var.set(f'นำเข้าสำเร็จ {result.processed:,} แถว • ข้ามแถวว่าง {result.skipped_blank:,}')
                    messagebox.showinfo('นำเข้าข้อมูลสำเร็จ',
                        f'ปลายทาง: {result.table_name}\nวิธี: {MODE_DISPLAY[result.mode]}\n'
                        f'นำเข้าแล้ว: {result.processed:,} แถว\nข้ามแถวว่าง: {result.skipped_blank:,} แถว')
                    self._fetch_tables()
                elif event == 'import_error':
                    self.is_importing = False
                    self.run_btn.configure(state='normal')
                    self.cancel_btn.configure(state='disabled')
                    self.status_var.set('นำเข้าไม่สำเร็จ • ตรวจสอบข้อความผิดพลาด')
                    messagebox.showerror('นำเข้าข้อมูลไม่สำเร็จ', args[0])
        except queue.Empty:
            pass
        self.after(120, self._drain_bus)

    def _load_demo(self):
        path = Path(__file__).parent / 'sample_data.csv'
        if not path.exists():
            return
        self.csv_path_var.set(str(path))
        self.user_var.set('import_user')
        self._load_preview()
        self.schema_var.set('label_idcard_mobile')
        self.table_var.set('rep_mobile_6908')
        # Demo's pretend schema is for display only; the status clearly shows
        # the session is NOT connected and the Run button cannot import.
        self.connected_label.configure(text='●  DEMO  /  ยังไม่เชื่อมต่อ',
                                       bg=PALE, fg=CYAN)
        self.status_var.set('โหมดสาธิตหน้าจอ • ยังไม่มีการเชื่อมต่อฐานข้อมูล')
        self._refresh_key_options()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CSV Import Studio v5 Space Edition')
    parser.add_argument('--demo', action='store_true', help='Open with a sample CSV and no MySQL connection')
    args = parser.parse_args()
    ImportStudio(demo=args.demo).mainloop()
