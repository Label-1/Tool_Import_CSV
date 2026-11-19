"""Multi-DB screen and real SQLite end-to-end UI workflow (xvfb on Linux)."""
import sqlite3
import time
from pathlib import Path
import tkinter as tk
from unittest.mock import patch

from app import ImportStudio


def wait_for(root, predicate, timeout=6):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        root.update()
        if predicate():
            return True
        time.sleep(.03)
    return False


def test_switch_backends_and_connect_sqlite(tmp_path):
    app = ImportStudio(demo=True)
    try:
        assert wait_for(app, lambda: app.preview is not None)
        for backend, schema in [('PostgreSQL','public'), ('MongoDB',''), ('SQLite','main')]:
            app.backend_var.set(backend)
            app._on_backend_changed()
            app.update()
            assert app.schema_var.get() == schema
            assert not app.connected
        assert app.sqlite_group.winfo_manager() == 'pack'
        assert app.network_group.winfo_manager() == ''
        app.sqlite_path_var.set(str(tmp_path/'mytest.db'))
        app._test_connection()
        assert wait_for(app, lambda: app.connected)
        assert app.schemas == ['main']
        assert app.backend_var.get() == 'SQLite'
        assert 'SQLite' in app.connected_label.cget('text')
        app.table_var.set('sample_records')
        assert wait_for(app, lambda: app.row_count is not None)
        opts = app._build_options()
        assert opts.table == 'sample_records'
        with patch('app.messagebox.askyesno',return_value=True),patch('app.messagebox.showinfo'):
            app._start_import()
            assert wait_for(app, lambda: not app.is_importing)
        with sqlite3.connect(tmp_path/'mytest.db') as conn:
            n = conn.execute('SELECT COUNT(*) FROM sample_records').fetchone()[0]
        assert n > 0
    finally:
        app.destroy()


def test_backend_switch_prevents_stale_state():
    app=ImportStudio(demo=False)
    try:
        app._post('connected','PostgreSQL',app._connection_signature(),['public'],'PostgreSQL 17')
        app.backend_var.set('SQLite')
        app._on_backend_changed()
        app._drain_bus()
        assert not app.connected
        app._post('connected','SQLite',app._connection_signature(),['main'],'SQLite 3')
        app._drain_bus()
        assert app.connected
        app._post('tables','PostgreSQL','public',['stale'])
        app._drain_bus()
        assert 'stale' not in app.tables
    finally:
        app.destroy()


def test_credentials_change_invalidates_connection(tmp_path):
    app = ImportStudio(demo=False)
    try:
        app.backend_var.set('SQLite')
        app._on_backend_changed()
        app.sqlite_path_var.set(str(tmp_path / 'old.db'))
        app._post('connected','SQLite', app._connection_signature(), ['main'], 'SQLite')
        app._drain_bus()
        assert app.connected
        app.sqlite_path_var.set(str(tmp_path / 'new.db'))
        assert not app.connected
        assert not app.tables
        assert 'ใหม่' in app.connected_label.cget('text')
    finally:
        app.destroy()
