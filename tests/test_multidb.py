"""Executable integration tests using a real temporary SQLite database."""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from importer_core import CSVSpec, DbSettings, ImportOptions, ColumnMapping, preview_csv
from database_backends import (
    open_connection, list_schemas, list_tables, list_columns, unique_keys,
    sql_identifier, run_import, _mongo_cast,
)


def make_options(tmp_path, headers, rows, *, mode='create', table='destination',
                 key='', create_schema=False, types=None):
    target = tmp_path / 'data.csv'
    with target.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    metadata = preview_csv(CSVSpec(str(target)))
    mappings = [ColumnMapping(i, h, h, (types or {}).get(h, 'TEXT')) for i,h in enumerate(headers)]
    return ImportOptions(CSVSpec(str(target)), DbSettings(str(tmp_path / 'target.db'), 0, '', ''),
                         'main', table, mode, mappings, create_schema=create_schema,
                         unique_key=key, expected_headers=metadata.headers,
                         expected_size=metadata.file_size, expected_mtime_ns=metadata.file_mtime_ns)


def query(path, statement):
    with sqlite3.connect(str(path)) as conn:
        return list(conn.execute(statement))


def test_sqlite_create_preview_exact_strings_and_unicode_column(tmp_path):
    opts = make_options(tmp_path, ['id','เลขบัตร','ชื่อ'],
                        [['A1','00123',"'นาย สมชาย"], ['A2','00456','ปัทมา']],
                        key='id', types={'id':'TEXT','เลขบัตร':'TEXT','ชื่อ':'VARCHAR(50)'})
    opts.mappings[2].target_name = 'ชื่อใหม่'
    opts.unique_key = 'id'
    result = run_import(opts,'SQLite')
    assert result.processed == 2
    assert query(tmp_path/'target.db', 'SELECT "id", "เลขบัตร", "ชื่อใหม่" FROM destination ORDER BY id') == [
        ('A1','00123',"'นาย สมชาย"), ('A2','00456','ปัทมา')]
    conn=open_connection(opts.db,'SQLite')
    try:
        assert list_schemas(conn,'SQLite') == ['main']
        assert list_tables(conn,'main','SQLite') == ['destination']
        assert [r['name'] for r in list_columns(conn,'main','destination','SQLite')] == ['id','เลขบัตร','ชื่อใหม่']
        assert unique_keys(conn,'main','destination','SQLite')[0] == ['id']
    finally:
        conn.close()


def test_sqlite_append_and_upsert(tmp_path):
    opts = make_options(tmp_path, ['id','name'],[['0001','old']], key='id')
    run_import(opts,'SQLite')
    append_opts = make_options(tmp_path,['id','name'],[['0002','added']],mode='append')
    run_import(append_opts,'SQLite')
    upsert = make_options(tmp_path,['id','name'],[['0001','new'],['0003','new3']],mode='upsert',key='id')
    run_import(upsert,'SQLite')
    assert query(tmp_path/'target.db', 'SELECT id,name FROM destination ORDER BY id') == [
        ('0001','new'),('0002','added'),('0003','new3')]


def test_sqlite_replace_keeps_layout_and_rolls_back_on_failure(tmp_path):
    opts = make_options(tmp_path,['id','amount'],[['1','2.0']], key='id',types={'id':'TEXT','amount':'TEXT'})
    run_import(opts,'SQLite')
    # The existing table has a UNIQUE key, so duplicates force a rollback.
    invalid = make_options(tmp_path,['id','amount'],[['2','value'],['2','duplicate']], mode='replace')
    with pytest.raises(sqlite3.IntegrityError):
        run_import(invalid,'SQLite')
    assert query(tmp_path/'target.db','SELECT id, amount FROM destination') == [('1','2.0')]
    valid = make_options(tmp_path,['id','amount'],[['3','3.50']],mode='replace')
    run_import(valid,'SQLite')
    assert query(tmp_path/'target.db','SELECT id, amount FROM destination') == [('3','3.50')]


def test_sqlite_create_invalid_rows_rolls_back_table_and_handles_cancel(tmp_path):
    opts = make_options(tmp_path,['id','col'],[['1','a'],['1','b']],key='id')
    with pytest.raises(sqlite3.IntegrityError):
        run_import(opts,'SQLite')
    assert query(tmp_path/'target.db',"SELECT name FROM sqlite_master WHERE type='table'") == []
    opts2 = make_options(tmp_path,['id','col'],[['1','a']], key='id')
    from importer_core import ImportCancelled
    with pytest.raises(ImportCancelled):
        run_import(opts2,'SQLite',is_cancelled=lambda: True)
    assert query(tmp_path/'target.db',"SELECT name FROM sqlite_master WHERE type='table'") == []


def test_sqlite_existing_requires_matching_columns(tmp_path):
    opts = make_options(tmp_path,['id','name'],[['a','one']])
    run_import(opts,'SQLite')
    invalid = make_options(tmp_path,['id','other'],[['b','two']],mode='append')
    with pytest.raises(ValueError,match='ไม่พบคอลัมน์'):
        run_import(invalid,'SQLite')
    assert query(tmp_path/'target.db','SELECT COUNT(*) FROM destination') == [(1,)]


def test_sqlite_new_db_preview_no_changes_until_import(tmp_path):
    opts = make_options(tmp_path,['id'],[['001']])
    assert not (tmp_path / 'target.db').exists()
    metadata = preview_csv(opts.csv_spec)
    assert metadata.rows == [['001']]
    assert not (tmp_path / 'target.db').exists()
    conn = open_connection(opts.db,'SQLite')
    conn.close()
    assert (tmp_path / 'target.db').exists()


def test_postgres_safe_identifiers_and_mongo_types():
    assert sql_identifier('ชื่อ', 'PostgreSQL') == '"ชื่อ"'
    assert sql_identifier('a"b', 'PostgreSQL') == '"a""b"'
    assert _mongo_cast('00123','TEXT',1,'id') == '00123'
    assert _mongo_cast('00012','INT',1,'id') == 12
    assert _mongo_cast('2026-01-02','DATE',1,'date').year == 2026
    with pytest.raises(ValueError):
        _mongo_cast('wrong','INT',1,'id')
    with pytest.raises(ValueError):
        sql_identifier('a\x00b','PostgreSQL')


def test_postgres_and_mongo_connection_validation(tmp_path):
    with pytest.raises((RuntimeError, ValueError)):
        open_connection(DbSettings('127.0.0.1',5432,'x','y'),'PostgreSQL')
    with pytest.raises((RuntimeError, ValueError)):
        open_connection(DbSettings('127.0.0.1',27017,'',''),'MongoDB')
