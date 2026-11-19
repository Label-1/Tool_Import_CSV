"""Additional database connectors for CSV Import Studio v6.

MySQL is delegated to the unchanged v5 importer. CSV parsing and row validation
are reused, while each database handles its own schema/collection semantics.
No secrets are saved and CSV input is never rewritten on disk.
"""
from __future__ import annotations

from datetime import datetime
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import sqlite3
import uuid
from typing import Callable, Optional

import importer_core as mysql
from importer_core import (
    ColumnMapping, DbSettings, ImportCancelled, ImportOptions, ImportResult,
    PartialImportError, _check_config, open_csv_reader,
    validate_simple_identifier,
)

BACKENDS = ('MySQL', 'PostgreSQL', 'SQLite', 'MongoDB')


def pg_identifier(name: str) -> str:
    _validate_field(name)
    if len(name.encode('utf-8')) > 63:
        raise ValueError(f'ชื่อ PostgreSQL ยาวเกิน 63 bytes: {name}')
    return '"' + name.replace('"', '""') + '"'


def sql_identifier(name: str, backend: str) -> str:
    _validate_field(name)
    if backend == 'PostgreSQL':
        return pg_identifier(name)
    return '"' + name.replace('"', '""') + '"'


def _validate_field(name: str):
    if not isinstance(name, str) or not name or len(name) > 64:
        raise ValueError('ชื่อคอลัมน์ต้องมีความยาว 1-64 อักขระ')
    if any(ord(c) < 32 or ord(c) == 127 for c in name) or name.endswith(' '):
        raise ValueError('ชื่อคอลัมน์มีอักขระควบคุมหรือช่องว่างท้ายชื่อ')


def _validate_mongo_field(name: str):
    _validate_field(name)
    if name.startswith('$') or '.' in name or '\x00' in name:
        raise ValueError(f'ชื่อฟิลด์ MongoDB ไม่รองรับ . หรือ $ นำหน้า: {name}')


def open_connection(settings: DbSettings, backend: str = 'MySQL', pg_database: str = 'postgres'):
    if backend == 'MySQL':
        return mysql.connect(settings)
    if backend == 'SQLite':
        target = Path(settings.host).expanduser()
        if not settings.host.strip():
            raise ValueError('กรุณาเลือกไฟล์ SQLite (.db)')
        if not target.parent.is_dir():
            raise ValueError('ไม่พบโฟลเดอร์สำหรับสร้างไฟล์ SQLite')
        conn = sqlite3.connect(str(target), timeout=30)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn
    if backend == 'PostgreSQL':
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError('ต้องติดตั้ง PostgreSQL driver: py -m pip install "psycopg[binary]"') from exc
        validate_simple_identifier(pg_database, 'PostgreSQL Database')
        return psycopg.connect(host=settings.host, port=settings.port,
                               user=settings.user, password=settings.password,
                               dbname=pg_database, connect_timeout=12)
    if backend == 'MongoDB':
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError('ต้องติดตั้ง MongoDB driver: py -m pip install pymongo') from exc
        kwargs = {'host': settings.host, 'port': settings.port, 'serverSelectionTimeoutMS': 10000,
                  'connectTimeoutMS': 10000, 'socketTimeoutMS': 600000}
        if settings.user:
            kwargs.update(username=settings.user, password=settings.password, authSource='admin')
        conn = MongoClient(**kwargs)
        try:
            conn.admin.command('ping')
        except Exception:
            conn.close()
            raise
        return conn
    raise ValueError(f'ไม่รองรับฐานข้อมูล: {backend}')


def server_version(conn, backend: str) -> str:
    if backend == 'MySQL':
        return str(conn.get_server_info())
    if backend == 'SQLite':
        return 'SQLite ' + sqlite3.sqlite_version
    if backend == 'MongoDB':
        try:
            return 'MongoDB ' + str(conn.server_info().get('version', ''))
        except Exception as exc:
            if getattr(exc, 'code', None) == 13:  # permission denied for buildInfo
                return 'MongoDB (connected)'
            raise
    with conn.cursor() as cur:
        cur.execute('SHOW server_version')
        return 'PostgreSQL ' + str(cur.fetchone()[0])


def list_schemas(conn, backend: str) -> list[str]:
    if backend == 'MySQL':
        return mysql.list_schemas(conn)
    if backend == 'SQLite':
        return ['main']
    if backend == 'MongoDB':
        try:
            return sorted(conn.list_database_names())
        except Exception as exc:
            if getattr(exc, 'code', None) == 13:  # no listDatabases privilege
                return []  # user may still enter an authorized DB manually
            raise
    with conn.cursor() as cur:
        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('information_schema','pg_catalog') AND schema_name NOT LIKE 'pg_toast%' ORDER BY schema_name")
        return [r[0] for r in cur.fetchall()]


def list_tables(conn, schema: str, backend: str) -> list[str]:
    validate_simple_identifier(schema, 'Schema / Database')
    if backend == 'MySQL':
        return mysql.list_tables(conn, schema)
    if backend == 'SQLite':
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    if backend == 'MongoDB':
        return sorted(conn[schema].list_collection_names())
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (schema,))
        return [r[0] for r in cur.fetchall()]


def list_columns(conn, schema: str, table: str, backend: str) -> list[dict]:
    validate_simple_identifier(schema, 'Schema / Database')
    validate_simple_identifier(table, 'Table / Collection')
    if backend == 'MySQL':
        return mysql.list_columns(conn, schema, table)
    if backend == 'SQLite':
        return [{'name': r[1], 'type': r[2], 'nullable': not r[3],
                 'key': r[5], 'default': r[4], 'extra': ''}
                for r in conn.execute(f'PRAGMA table_info({sql_identifier(table, backend)})')]
    if backend == 'MongoDB':
        # MongoDB is schema-less: a bounded sample informs the UI, not a constraint.
        seen = {}
        for doc in conn[schema][table].find({}, limit=100):
            for key, val in doc.items():
                if key not in seen:
                    seen[key] = {'name': key, 'type': type(val).__name__.upper(), 'nullable': True,
                                 'key': '_id' if key == '_id' else '', 'default': None, 'extra': ''}
        return list(seen.values())
    with conn.cursor() as cur:
        cur.execute("""SELECT column_name, data_type, is_nullable, column_default, is_identity, is_generated
                    FROM information_schema.columns WHERE table_schema=%s AND table_name=%s
                    ORDER BY ordinal_position""", (schema, table))
        return [{'name': r[0], 'type': r[1], 'nullable': r[2] == 'YES',
                 'default': r[3], 'key': '',
                 'extra': 'generated' if r[5] != 'NEVER' else ('identity' if r[4] == 'YES' else '')}
                for r in cur.fetchall()]


def unique_keys(conn, schema: str, table: str, backend: str) -> tuple[list[str], int]:
    if backend == 'MySQL':
        return mysql.unique_key_columns(conn, schema, table)
    if backend == 'SQLite':
        indexes = []
        quoted = sql_identifier(table, backend)
        for row in conn.execute(f'PRAGMA index_list({quoted})'):
            if row[2] and not row[4]:  # skip partial indexes: ON CONFLICT(key) cannot target them alone
                indexes.append([r[2] for r in conn.execute(f'PRAGMA index_info({sql_identifier(row[1], backend)})')])
        pk = [r[1] for r in conn.execute(f'PRAGMA table_info({quoted})') if r[5] > 0]
        if len(pk) == 1 and pk not in indexes:
            indexes.append(pk)
        single = [r[0] for r in indexes if len(r) == 1 and r[0]]
        return sorted(set(single)), len(indexes)
    if backend == 'MongoDB':
        indexes = [list(i['key']) for i in conn[schema][table].list_indexes() if i.get('unique') and not i.get('partialFilterExpression')]
        single = [r[0] for r in indexes if len(r) == 1]
        return sorted(set(single)), len(indexes)
    with conn.cursor() as cur:
        # PostgreSQL ON CONFLICT works with an existing *unique index*, even
        # when created using CREATE UNIQUE INDEX rather than a named constraint.
        # Partial / expression / multi-column indexes are not eligible for the
        # app's single-column-key workflow.
        cur.execute("""SELECT idx.relname, att.attname
                     FROM pg_catalog.pg_index ind
                     JOIN pg_catalog.pg_class tbl ON tbl.oid=ind.indrelid
                     JOIN pg_catalog.pg_namespace ns ON ns.oid=tbl.relnamespace
                     JOIN pg_catalog.pg_class idx ON idx.oid=ind.indexrelid
                     JOIN pg_catalog.pg_attribute att
                       ON att.attrelid=tbl.oid AND att.attnum=ind.indkey[0]
                     WHERE ns.nspname=%s AND tbl.relname=%s
                       AND ind.indisunique AND ind.indisvalid
                       AND ind.indpred IS NULL AND ind.indexprs IS NULL
                       AND ind.indnkeyatts=1
                     ORDER BY idx.relname""", (schema, table))
        keys = [row[1] for row in cur.fetchall()]
        return sorted(set(keys)), len(keys)



def _dtype_pg(dtype: str) -> str:
    return {'LONGTEXT': 'TEXT', 'DOUBLE': 'DOUBLE PRECISION',
            'DATETIME': 'TIMESTAMP', 'INT': 'INTEGER',
            'BIGINT': 'BIGINT', 'DECIMAL(18,2)': 'DECIMAL(18,2)'}.get(dtype, dtype)


def _dtype_sqlite(dtype: str) -> str:
    if dtype in ('INT', 'BIGINT'):
        return 'INTEGER'
    if dtype in ('DOUBLE', 'DECIMAL(18,2)'):
        return 'REAL'
    return 'TEXT'  # Dates and VARCHAR are stored as text, preserving CSV representation.


def _validate_snapshot(options: ImportOptions):
    stat = os.stat(options.csv_spec.path)
    if options.expected_size is not None and stat.st_size != options.expected_size:
        raise ValueError('ไฟล์เปลี่ยนขนาดหลัง Preview กรุณาอ่าน CSV ใหม่')
    if options.expected_mtime_ns is not None and stat.st_mtime_ns != options.expected_mtime_ns:
        raise ValueError('ไฟล์เปลี่ยนแปลงหลัง Preview กรุณาอ่าน CSV ใหม่')
    return stat


def _read_selected(options: ImportOptions, selected: list[ColumnMapping]):
    file, reader, headers, _, _ = open_csv_reader(options.csv_spec)
    try:
        if options.expected_headers is not None and headers != options.expected_headers:
            raise ValueError('ชื่อคอลัมน์ CSV เปลี่ยนหลัง Preview')
        for m in selected:
            if (m.source_index < 0 or m.source_index >= len(headers)
                or headers[m.source_index] != m.source_name):
                raise ValueError(f'Mapping ของ {m.source_name} ไม่ตรงกับ CSV')
    except Exception:
        file.close()
        raise
    return file, reader, headers


def _row_values(row, selected, header_count, line_num):
    if not row or all(v == '' for v in row):
        return None
    if len(row) > header_count:
        raise ValueError(f'บรรทัด {line_num}: จำนวนคอลัมน์เกิน Header')
    row = row + [''] * (header_count - len(row))
    result = []
    for m in selected:
        value = row[m.source_index]
        if '\x00' in value:
            raise ValueError(f'บรรทัด {line_num}: พบ NUL ในคอลัมน์ {m.source_name}')
        result.append(value)
    return result


def _check_existing_columns(columns, selected, backend):
    lookup = {col['name'].casefold(): col for col in columns}
    if not lookup:
        raise ValueError('ไม่พบโครงสร้าง Table ปลายทาง')
    used = set()
    for m in selected:
        col = lookup.get(m.target_name.casefold())
        if col is None:
            raise ValueError(f'ไม่พบคอลัมน์ {m.target_name} ใน Table ปลายทาง')
        if col['name'].casefold() in used:
            raise ValueError(f'เลือกคอลัมน์ซ้ำ: {m.target_name}')
        m.target_name = col['name']
        used.add(m.target_name.casefold())
    missing = [c['name'] for c in columns
               if c['name'].casefold() not in used and not c['nullable']
               and c['default'] is None and 'generated' not in c['extra'].lower()
               and 'identity' not in c['extra'].lower()]
    if missing:
        raise ValueError('CSV ไม่มีคอลัมน์ที่ Table ต้องใช้: ' + ', '.join(missing[:6]))


def run_import(options: ImportOptions, backend='MySQL', pg_database='postgres',
               progress: Optional[Callable[[int, int, str], None]]=None,
               is_cancelled: Optional[Callable[[], bool]]=None) -> ImportResult:
    if backend == 'MySQL':
        return mysql.run_import(options, progress=progress, is_cancelled=is_cancelled)
    if backend not in BACKENDS:
        raise ValueError('ประเภทฐานข้อมูลไม่รองรับ')
    # Only MySQL restricts TEXT keys; PostgreSQL, SQLite and MongoDB can index
    # text fields. The other CSV/mapping validations remain identical to v5.
    opts_to_check = replace(options, unique_key='') if options.mode == 'create' and options.unique_key else options
    selected = _check_config(opts_to_check)
    if options.mode == 'create' and options.unique_key and options.unique_key not in [m.target_name for m in selected]:
        raise ValueError('Unique Key ไม่ตรงกับคอลัมน์ที่เลือก')
    if backend == 'SQLite':
        if options.schema != 'main' or options.create_schema:
            raise ValueError('SQLite ใช้ Schema main เท่านั้น')
    if backend == 'MongoDB':
        for m in selected:
            _validate_mongo_field(m.target_name)
    if backend == 'PostgreSQL':
        for m in selected:
            pg_identifier(m.target_name)
    stat = _validate_snapshot(options)
    file, reader, headers = _read_selected(options, selected)
    conn = None
    try:
        conn = open_connection(options.db, backend, pg_database)
        if backend == 'MongoDB':
            return _run_mongo(conn, options, selected, reader, len(headers), stat,
                              progress, is_cancelled)
        return _run_sql(conn, options, selected, reader, len(headers), stat,
                        backend, progress, is_cancelled, file)
    finally:
        file.close()
        if conn is not None:
            conn.close()


def _run_sql(conn, options, selected, reader, header_count, stat, backend, progress, is_cancelled, csv_file=None):
    q = lambda name: sql_identifier(name, backend)
    table = q(options.table)
    qualified = f'{q(options.schema)}.{table}' if backend == 'PostgreSQL' else table
    key = options.unique_key
    processed, blanks = 0, 0
    staging = None
    try:
        if backend == 'SQLite':
            # Ensure CREATE and REPLACE roll back fully on failed/cancelled imports.
            conn.execute('BEGIN IMMEDIATE')
        existing_schemas = list_schemas(conn, backend)
        if options.create_schema:
            if backend != 'PostgreSQL' or options.mode != 'create':
                raise ValueError('สร้าง Schema ได้เฉพาะ PostgreSQL/Create ใหม่')
            if options.schema in existing_schemas:
                raise ValueError('Schema นี้มีอยู่แล้ว')
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA {q(options.schema)}')
        elif options.schema not in existing_schemas:
            raise ValueError(f'ไม่พบ Schema {options.schema}')
        existing_tables = list_tables(conn, options.schema, backend)
        if options.mode == 'create':
            if options.table in existing_tables:
                raise ValueError('Table นี้มีอยู่แล้ว')
            staging = '__import_' + uuid.uuid4().hex[:12]
            target = f'{q(options.schema)}.{q(staging)}' if backend == 'PostgreSQL' else q(staging)
            columns_sql = [f'{q(m.target_name)} {_dtype_pg(m.data_type) if backend == "PostgreSQL" else _dtype_sqlite(m.data_type)}'
                           for m in selected]
            if key:
                columns_sql.append(f'UNIQUE ({q(key)})')
            ddl = f'CREATE TABLE {target} ({", ".join(columns_sql)})'
            if backend == 'SQLite':
                conn.execute(ddl)
            else:
                with conn.cursor() as cur:
                    cur.execute(ddl)
            qualified = target
        else:
            if options.table not in existing_tables:
                raise ValueError('ไม่พบ Table ปลายทาง')
            cols_meta = list_columns(conn, options.schema, options.table, backend)
            _check_existing_columns(cols_meta, selected, backend)
            if options.mode == 'upsert':
                keys, _ = unique_keys(conn, options.schema, options.table, backend)
                if key not in keys or key not in [m.target_name for m in selected]:
                    raise ValueError('Upsert ต้องเลือก Unique Key ที่มีอยู่จริงและจับคู่ใน CSV')
            if options.mode == 'replace':
                sql = f'DELETE FROM {qualified}'
                if backend == 'SQLite':
                    conn.execute(sql)
                else:
                    with conn.cursor() as cur:
                        cur.execute(sql)
        cols = [m.target_name for m in selected]
        placeholders = ','.join(['?' if backend == 'SQLite' else '%s'] * len(cols))
        insert = f'INSERT INTO {qualified} ({", ".join(q(c) for c in cols)}) VALUES ({placeholders})'
        if options.mode == 'upsert':
            mutable = [c for c in cols if c != key]
            if not mutable:
                raise ValueError('Upsert ต้องมีคอลัมน์ข้อมูลอื่นนอกเหนือจาก Key')
            insert += f' ON CONFLICT ({q(key)}) DO UPDATE SET ' + ', '.join(
                f'{q(c)}=excluded.{q(c)}' for c in mutable)
        batch = []
        def flush():
            nonlocal batch
            if not batch:
                return
            if backend == 'SQLite':
                conn.executemany(insert, batch)
            else:
                with conn.cursor() as cur:
                    cur.executemany(insert, batch)
            batch = []
            if progress:
                try:
                    amount = csv_file.buffer.tell() if csv_file else 0
                    percentage = min(99, round(amount / max(stat.st_size, 1) * 100))
                except (AttributeError, OSError):
                    percentage = 0
                progress(percentage, processed, f'นำเข้าแล้ว {processed:,} แถว')
        for row in reader:
            if is_cancelled and is_cancelled():
                raise ImportCancelled('ยกเลิกการนำเข้า')
            values = _row_values(row, selected, header_count, reader.line_num)
            if values is None:
                blanks += 1
                continue
            batch.append(values)
            processed += 1
            if len(batch) >= 400:
                flush()
        flush()
        if is_cancelled and is_cancelled():
            raise ImportCancelled('ยกเลิกการนำเข้า')
        if staging:
            rename = f'ALTER TABLE {qualified} RENAME TO {q(options.table)}'
            if backend == 'SQLite':
                conn.execute(rename)
            else:
                with conn.cursor() as cur:
                    cur.execute(rename)
        conn.commit()
        if progress:
            progress(100, processed, 'นำเข้าสำเร็จ')
        return ImportResult(processed, f'{options.schema}.{options.table}', blanks, options.mode, 'สำเร็จ')
    except Exception:
        conn.rollback()
        raise


def _mongo_cast(value: str, dtype: str, line_num: int, name: str):
    # Unlike SQL, BSON is explicitly typed. TEXT/default is stored verbatim.
    if dtype in ('TEXT', 'LONGTEXT') or dtype.startswith('VARCHAR'):
        return value
    if value == '':
        raise ValueError(f'บรรทัด {line_num}: ค่า {name} ว่าง แต่เลือกประเภท {dtype}')
    try:
        if dtype in ('INT', 'BIGINT'):
            converted = int(value)
            if dtype == 'INT' and not -(2**31) <= converted < 2**31:
                raise ValueError('INT ต้องอยู่ในช่วง 32-bit')
            if dtype == 'BIGINT' and not -(2**63) <= converted < 2**63:
                raise ValueError('BIGINT ต้องอยู่ในช่วง 64-bit')
            return converted
        if dtype == 'DOUBLE':
            converted = float(value)
            if not -float('inf') < converted < float('inf'):
                raise ValueError('ไม่รองรับ Infinity/NaN')
            return converted
        if dtype == 'DECIMAL(18,2)':
            from bson.decimal128 import Decimal128
            converted = Decimal(value)
            if not converted.is_finite():
                raise ValueError('ไม่รองรับ Infinity/NaN')
            return Decimal128(converted)
        if dtype in ('DATE', 'DATETIME'):
            val = datetime.fromisoformat(value)
            return val.replace(tzinfo=None)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f'บรรทัด {line_num}: ค่า {name} ไม่เข้ากับ {dtype}: {value!r}') from exc
    return value


def _run_mongo(conn, options, selected, reader, header_count, stat, progress, is_cancelled):
    from pymongo import UpdateOne
    db = conn[options.schema]
    collections = db.list_collection_names()
    if options.mode == 'create' and options.table in collections:
        raise ValueError('Collection นี้มีอยู่แล้ว')
    if options.mode != 'create' and options.table not in collections:
        raise ValueError('ไม่พบ Collection ปลายทาง')
    key = options.unique_key
    if options.mode == 'upsert':
        keys, _ = unique_keys(conn, options.schema, options.table, 'MongoDB')
        if len(selected) < 2:
            raise ValueError('Upsert ต้องมีฟิลด์อื่นนอกเหนือจาก Unique Key อย่างน้อย 1 ฟิลด์')
        if key not in keys or key not in [m.target_name for m in selected]:
            raise ValueError('MongoDB Upsert ต้องมี Unique Index ของคีย์ที่เลือก')
    staging = None
    coll = db[options.table]
    if options.mode in ('create', 'replace'):
        staging = '__import_' + uuid.uuid4().hex[:12]
        if options.mode == 'replace':
            # Preserve indexes before swapping: a replacement must not silently
            # weaken the destination's uniqueness requirements.
            infos = list(db.list_collections(filter={'name': options.table}))
            if infos and infos[0].get('options'):
                raise ValueError('Collection มี options พิเศษ ไม่รองรับ Replace อัตโนมัติ (เพื่อรักษา validation/options เดิม)')
        coll = db.create_collection(staging)
    processed, blanks, committed = 0, 0, 0
    try:
        if options.mode == 'create' and key:
            coll.create_index([(key, 1)], unique=True)
        if options.mode == 'replace':
            for ind in db[options.table].list_indexes():
                if ind['name'] != '_id_':
                    kwargs = {k: ind[k] for k in ('unique', 'sparse', 'expireAfterSeconds',
                                               'partialFilterExpression', 'collation', 'hidden') if k in ind}
                    coll.create_index(list(ind['key'].items()), name=ind['name'], **kwargs)
        batch = []
        def flush():
            nonlocal batch, committed
            if not batch:
                return
            if options.mode == 'upsert':
                commands = []
                for doc in batch:
                    query = {key: doc[key]}
                    update_doc = {k: v for k, v in doc.items() if k != '_id'}
                    update = {'$set': update_doc}
                    if '_id' in doc and key != '_id':
                        update['$setOnInsert'] = {'_id': doc['_id']}
                    commands.append(UpdateOne(query, update, upsert=True))
                coll.bulk_write(commands, ordered=True)
            else:
                coll.insert_many(batch, ordered=True)
            batch = []
            if options.mode in ('append', 'upsert'):
                committed = processed
            if progress:
                progress(min(99, round(processed / max(processed + 100, 1) * 100)),
                         processed, f'นำเข้าแล้ว {processed:,} เอกสาร')
        for row in reader:
            if is_cancelled and is_cancelled():
                raise ImportCancelled('ยกเลิกการนำเข้า')
            values = _row_values(row, selected, header_count, reader.line_num)
            if values is None:
                blanks += 1
                continue
            doc = {m.target_name: _mongo_cast(val, m.data_type, reader.line_num, m.target_name)
                   for m, val in zip(selected, values)}
            batch.append(doc)
            processed += 1
            if len(batch) >= 400:
                flush()
        flush()
        if is_cancelled and is_cancelled():
            raise ImportCancelled('ยกเลิกการนำเข้า')
        if staging:
            # A successful staging write swaps atomically on supported MongoDB
            # deployments. No old collection is deleted before staging is ready.
            coll.rename(options.table, dropTarget=(options.mode == 'replace'))
            staging = None
        if progress:
            progress(100, processed, 'นำเข้าสำเร็จ')
        return ImportResult(processed, f'{options.schema}.{options.table}', blanks, options.mode, 'สำเร็จ')
    except Exception as exc:
        if options.mode in ('append', 'upsert') and committed:
            raise PartialImportError(exc, committed) from exc
        raise
    finally:
        if staging:
            try:
                db.drop_collection(staging)
            except Exception:
                pass
