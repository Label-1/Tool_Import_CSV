"""CSV -> MySQL import logic. No UI dependencies, values are always parameterized."""
from __future__ import annotations

import codecs
import csv
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


MODES = ("create", "append", "upsert", "replace")
# Explicit allowlist: CSV values are never cleaned or rewritten. MySQL handles
# conversion only when the user intentionally selects a non-text SQL type.
TYPES = (
    "TEXT", "VARCHAR(50)", "VARCHAR(100)", "VARCHAR(255)",
    "LONGTEXT", "INT", "BIGINT", "DECIMAL(18,2)", "DOUBLE",
    "DATE", "DATETIME",
)
INDEXABLE_TYPES = {"VARCHAR(50)", "VARCHAR(100)", "VARCHAR(255)",
                   "INT", "BIGINT", "DECIMAL(18,2)", "DOUBLE", "DATE", "DATETIME"}
DELIMITERS = {"Auto": None, "Comma (,)": ",", "Semicolon (; )": ";", "Tab": "\t", "Pipe (|)": "|"}
ENCODINGS = {"Auto": None, "UTF-8": "utf-8", "UTF-8 with BOM": "utf-8-sig", "Thai Windows (CP874)": "cp874", "Thai TIS-620": "tis-620"}
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class CSVSpec:
    path: str
    encoding: str = "Auto"
    delimiter: str = "Auto"


@dataclass
class FilePreview:
    headers: list[str]
    rows: list[list[str]]
    encoding: str
    delimiter: str
    file_size: int
    file_mtime_ns: int


@dataclass(frozen=True)
class CSVRowCount:
    """CSV records eligible for import (excludes header and completely blank records)."""
    data_rows: int
    blank_rows: int


@dataclass
class ColumnMapping:
    source_index: int
    source_name: str
    target_name: str
    data_type: str = "TEXT"
    include: bool = True


@dataclass
class DbSettings:
    host: str
    port: int
    user: str
    password: str


@dataclass
class ImportOptions:
    csv_spec: CSVSpec
    db: DbSettings
    schema: str
    table: str
    mode: str
    mappings: list[ColumnMapping]
    create_schema: bool = False
    unique_key: str = ""
    expected_headers: Optional[list[str]] = None
    expected_size: Optional[int] = None
    expected_mtime_ns: Optional[int] = None


@dataclass
class ImportResult:
    processed: int
    table_name: str
    skipped_blank: int
    mode: str
    note: str


class ImportCancelled(RuntimeError):
    pass


class PartialImportError(RuntimeError):
    def __init__(self, error: Exception, committed: int):
        super().__init__(f"นำเข้าไม่สำเร็จ: {error}\nแถวที่บันทึกไปแล้ว: {committed:,} (โหมดเพิ่ม/อัปเดตอาจเกิดการนำเข้าบางส่วน)")
        self.committed = committed


def validate_simple_identifier(name: str, label: str) -> str:
    if not name or len(name) > 64 or not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"{label} ต้องขึ้นต้นด้วย A-Z หรือ _ และประกอบด้วย A-Z, 0-9, _ (ไม่เกิน 64 ตัวอักษร)")
    return name


def quote_identifier(name: str) -> str:
    """Quotes Unicode (including Thai) SQL identifiers, never SQL values."""
    if not isinstance(name, str) or not name or len(name) > 64 or name.endswith(" "):
        raise ValueError(f"ชื่อคอลัมน์ไม่ถูกต้อง: {name!r} (1-64 ตัวอักษร, ห้ามลงท้ายด้วยช่องว่าง)")
    if any(ord(c) < 32 or ord(c) == 127 for c in name) or "`" in name or "." in name:
        raise ValueError(f"ชื่อคอลัมน์มีอักขระไม่อนุญาต: {name!r}")
    return "`" + name + "`"


def quote_table(schema: str, table: str) -> str:
    validate_simple_identifier(schema, "Schema")
    validate_simple_identifier(table, "Table")
    return quote_identifier(schema) + "." + quote_identifier(table)


def _decode_sample(sample: bytes, user_choice: str) -> tuple[str, str]:
    selected = ENCODINGS.get(user_choice)
    if user_choice not in ENCODINGS:
        raise ValueError(f"ไม่รู้จัก Encoding: {user_choice}")
    if selected:
        return selected, sample.decode(selected)
    # Incremental decode accepts an incomplete UTF-8 sequence at the sample boundary.
    try:
        decoded = codecs.getincrementaldecoder("utf-8-sig")("strict").decode(sample, final=False)
        return "utf-8-sig", decoded
    except UnicodeDecodeError:
        pass
    for codec in ("cp874", "tis-620"):
        try:
            return codec, sample.decode(codec)
        except UnicodeDecodeError:
            continue
    raise ValueError("ไม่สามารถอ่าน Encoding อัตโนมัติได้ กรุณาเลือก Encoding เอง")


def resolve_csv_format(spec: CSVSpec) -> tuple[str, str]:
    path = Path(spec.path)
    if not path.is_file():
        raise ValueError("ไม่พบไฟล์ที่เลือก")
    if path.suffix.lower() not in (".csv", ".txt"):
        raise ValueError("ระบบเวอร์ชันนี้รองรับไฟล์ .csv หรือ .txt เท่านั้น")
    with path.open("rb") as binary:
        sample = binary.read(65536)
    if not sample:
        raise ValueError("ไฟล์ว่าง ไม่มีข้อมูลให้นำเข้า")
    encoding, text = _decode_sample(sample, spec.encoding)
    delimiter = DELIMITERS.get(spec.delimiter)
    if spec.delimiter not in DELIMITERS:
        raise ValueError(f"ไม่รู้จักตัวคั่นข้อมูล: {spec.delimiter}")
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
        except csv.Error:
            first_line = text.splitlines()[0] if text.splitlines() else ""
            delimiter = max((",", ";", "\t", "|"), key=lambda ch: first_line.count(ch))
            if delimiter not in first_line:
                delimiter = ","
    return encoding, delimiter


def _clean_headers(raw: list[str]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for idx, value in enumerate(raw):
        original = (value or "").strip() or f"column_{idx+1}"
        name = original[:64]
        stem = name
        n = seen.get(stem.casefold(), 0) + 1
        if n > 1:
            name = f"{stem[:64-len(str(n))-2]}__{n}"
        while name.casefold() in {v.casefold() for v in headers}:
            n += 1
            name = f"{stem[:64-len(str(n))-2]}__{n}"
        seen[stem.casefold()] = n
        headers.append(name)
    return headers


def open_csv_reader(spec: CSVSpec):
    """Return (file, csv.reader, headers, encoding, delimiter). Caller closes file."""
    encoding, delimiter = resolve_csv_format(spec)
    csv.field_size_limit(1024 * 1024 * 128)
    file = open(spec.path, "r", encoding=encoding, newline="")
    try:
        reader = csv.reader(file, delimiter=delimiter, strict=True)
        raw_headers = next(reader, None)
        if raw_headers is None or not any(c.strip() for c in raw_headers):
            raise ValueError("ไม่พบชื่อคอลัมน์ในแถวแรกของ CSV")
        headers = _clean_headers(raw_headers)
        return file, reader, headers, encoding, delimiter
    except Exception:
        file.close()
        raise


def preview_csv(spec: CSVSpec, limit: int = 20) -> FilePreview:
    f, reader, headers, encoding, delimiter = open_csv_reader(spec)
    rows: list[list[str]] = []
    try:
        for line in reader:
            if not line or all(not val for val in line):
                continue
            if len(line) > len(headers):
                raise ValueError(f"แถว {reader.line_num} มีข้อมูล {len(line)} คอลัมน์ แต่ Header มี {len(headers)} คอลัมน์")
            rows.append(line + [""] * (len(headers) - len(line)))
            if len(rows) >= limit:
                break
    finally:
        f.close()
    st = os.stat(spec.path)
    return FilePreview(headers, rows, encoding, delimiter, st.st_size, st.st_mtime_ns)


def count_csv_rows(
    spec: CSVSpec,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> CSVRowCount:
    """Stream the entire file to count importable CSV rows without loading them.

    Count CSV *records*, not physical lines: quoted cells can span lines.
    Apply the same blank-row and over-wide-row logic as run_import().
    Suitable for a GUI background worker on large files.
    """
    original = os.stat(spec.path)
    f, reader, headers, _, _ = open_csv_reader(spec)
    count = 0
    blanks = 0
    try:
        for row in reader:
            if is_cancelled and (count + blanks) % 1024 == 0 and is_cancelled():
                raise ImportCancelled('ยกเลิกการนับจำนวนแถว')
            if not row or all(value == '' for value in row):
                blanks += 1
                continue
            if len(row) > len(headers):
                raise ValueError(
                    f'แถว CSV ที่บรรทัด {reader.line_num} มี {len(row)} คอลัมน์ เกิน Header {len(headers)} คอลัมน์'
                )
            count += 1
    finally:
        f.close()
    current = os.stat(spec.path)
    if current.st_size != original.st_size or current.st_mtime_ns != original.st_mtime_ns:
        raise ValueError('ไฟล์เปลี่ยนแปลงระหว่างการนับ กรุณาอ่าน Preview ใหม่')
    return CSVRowCount(count, blanks)


def _mysql_driver():
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("ยังไม่ได้ติดตั้ง PyMySQL: เปิด Command Prompt แล้วรัน py -m pip install pymysql") from exc
    return pymysql


def connect(settings: DbSettings):
    pymysql = _mysql_driver()
    return pymysql.connect(
        host=settings.host.strip(),
        port=int(settings.port),
        user=settings.user.strip(),
        password=settings.password,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=12,
        read_timeout=600,
        write_timeout=600,
    )


def list_schemas(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        return sorted(row[0] for row in cur.fetchall())


def list_tables(conn, schema: str) -> list[str]:
    validate_simple_identifier(schema, "Schema")
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME", (schema,))
        return [row[0] for row in cur.fetchall()]


def list_columns(conn, schema: str, table: str) -> list[dict]:
    qualified = quote_table(schema, table)
    with conn.cursor() as cur:
        cur.execute(f"SHOW FULL COLUMNS FROM {qualified}")
        rows = cur.fetchall()
        return [
            {"name": r[0], "type": r[1], "nullable": r[3] == "YES", "key": r[4], "default": r[5], "extra": r[6] or ""}
            for r in rows
        ]


def unique_key_columns(conn, schema: str, table: str) -> tuple[list[str], int]:
    qualified = quote_table(schema, table)
    with conn.cursor() as cur:
        cur.execute(f"SHOW INDEX FROM {qualified}")
        rows = cur.fetchall()
    # SHOW INDEX columns: Table, Non_unique, Key_name, Seq_in_index, Column_name
    indices: dict[str, list[str]] = {}
    for row in rows:
        if row[1] == 0:
            indices.setdefault(row[2], []).append(row[4])
    eligible = [cols[0] for cols in indices.values() if len(cols) == 1 and cols[0]]
    return eligible, len(indices)


def _check_config(options: ImportOptions) -> list[ColumnMapping]:
    validate_simple_identifier(options.schema, "Schema")
    validate_simple_identifier(options.table, "Table")
    if options.mode not in MODES:
        raise ValueError("ประเภทการนำเข้าไม่ถูกต้อง")
    if options.create_schema and options.mode != "create":
        raise ValueError("สร้าง Schema ใหม่ได้เฉพาะโหมด Create New")
    mappings = sorted((m for m in options.mappings if m.include), key=lambda x: x.source_index)
    if not mappings:
        raise ValueError("ต้องเลือกอย่างน้อย 1 คอลัมน์")
    dest_names = set()
    sources = set()
    for m in mappings:
        quote_identifier(m.target_name)
        if options.mode == "create" and m.data_type not in TYPES:
            raise ValueError(f"ประเภทข้อมูลไม่รองรับ: {m.data_type}")
        if m.target_name.casefold() in dest_names:
            raise ValueError(f"คอลัมน์ปลายทางซ้ำ: {m.target_name}")
        if m.source_index in sources:
            raise ValueError("เลือกคอลัมน์ CSV ซ้ำ")
        sources.add(m.source_index)
        dest_names.add(m.target_name.casefold())
    if options.mode == "create" and options.unique_key:
        key_maps = [m for m in mappings if m.target_name == options.unique_key]
        if not key_maps:
            raise ValueError("ไม่พบคอลัมน์ที่เลือกเป็น Unique Key")
        if key_maps[0].data_type not in INDEXABLE_TYPES:
            raise ValueError("Unique Key ต้องใช้ชนิดข้อมูลที่ทำ Index ได้ เช่น VARCHAR, INT หรือ DATE")
    return mappings


def _build_insert_sql(qualified: str, cols: list[str], batch_length: int, mode: str, key: str = "", use_alias: bool = True) -> str:
    column_sql = ", ".join(quote_identifier(c) for c in cols)
    placeholders = "(" + ",".join("%s" for _ in cols) + ")"
    values = ",".join([placeholders] * batch_length)
    sql = f"INSERT INTO {qualified} ({column_sql}) VALUES {values}"
    if mode == "upsert":
        mutable = [c for c in cols if c != key]
        if not mutable:
            raise ValueError("Upsert ต้องเลือกคอลัมน์ข้อมูลอื่นนอกเหนือจาก Key อย่างน้อย 1 คอลัมน์")
        if use_alias:
            sql += " AS _incoming ON DUPLICATE KEY UPDATE " + ", ".join(
                f"{quote_identifier(c)} = _incoming.{quote_identifier(c)}" for c in mutable
            )
        else:
            sql += " ON DUPLICATE KEY UPDATE " + ", ".join(
                f"{quote_identifier(c)} = VALUES({quote_identifier(c)})" for c in mutable
            )
    return sql


def _server_supports_alias(conn) -> bool:
    version = str(conn.get_server_info()).lower()
    if "mariadb" in version:
        return False
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return False
    return tuple(int(n) for n in match.groups()) >= (8, 0, 19)


def run_import(
    options: ImportOptions,
    progress: Optional[Callable[[int, int, str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> ImportResult:
    """Run import in background thread. Create is staged; Replace rolls back on errors.

    Append/Upsert commit per batch (500 rows or ~1MB), so an error may leave
    previously committed batches; errors state that partial row count explicitly.
    """
    selected = _check_config(options)
    stat = os.stat(options.csv_spec.path)
    if options.expected_size is not None and stat.st_size != options.expected_size:
        raise ValueError("ไฟล์มีการแก้ไขขนาดหลัง Preview กรุณากดอ่านไฟล์ใหม่")
    if options.expected_mtime_ns is not None and stat.st_mtime_ns != options.expected_mtime_ns:
        raise ValueError("ไฟล์มีการแก้ไขหลัง Preview กรุณากดอ่านไฟล์ใหม่")
    f, reader, headers, _encoding, _delimiter = open_csv_reader(options.csv_spec)
    conn = None
    temp_name = None
    committed = 0
    processed = 0
    blank_count = 0
    total_bytes = max(stat.st_size, 1)
    try:
        if options.expected_headers is not None and headers != options.expected_headers:
            raise ValueError("ชื่อคอลัมน์ CSV เปลี่ยนหลัง Preview กรุณาอ่านไฟล์ใหม่")
        for m in selected:
            if m.source_index < 0 or m.source_index >= len(headers) or headers[m.source_index] != m.source_name:
                raise ValueError(f"Mapping ของ {m.source_name} ไม่ตรงกับ CSV ปัจจุบัน")
        if progress:
            progress(1, 0, "ตรวจสอบ Schema, Table และสิทธิ์การเข้าถึง...")
        conn = connect(options.db)
        with conn.cursor() as cur:
            cur.execute("SELECT @@SESSION.sql_mode")
            sql_mode = (cur.fetchone() or [""])[0] or ""
            if "STRICT_TRANS_TABLES" not in sql_mode.upper() and "STRICT_ALL_TABLES" not in sql_mode.upper():
                cur.execute("SET SESSION sql_mode = %s", (sql_mode + ",STRICT_TRANS_TABLES").strip(","))
        with conn.cursor() as cur:
            cur.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", (options.schema,))
            schema_exists = cur.fetchone() is not None
            if options.create_schema:
                if schema_exists:
                    raise ValueError(f"Schema {options.schema} มีอยู่แล้ว กรุณาปิดตัวเลือกสร้าง Schema ใหม่")
                cur.execute(f"CREATE DATABASE {quote_identifier(options.schema)} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                schema_exists = True
            if not schema_exists:
                raise ValueError(f"ไม่พบ Schema {options.schema} หรือไม่มีสิทธิ์เข้าถึง")
            cur.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND TABLE_TYPE = 'BASE TABLE'",
                (options.schema, options.table),
            )
            table_exists = cur.fetchone() is not None
            if options.mode == "create" and table_exists:
                raise ValueError("Table นี้มีอยู่แล้ว กรุณาตั้งชื่อใหม่ หรือเลือก Append / Upsert / Replace")
            if options.mode != "create" and not table_exists:
                raise ValueError("ไม่พบ Table ปลายทาง กรุณาเลือก Table ที่มีอยู่")

        key = options.unique_key
        if options.mode == "create":
            temp_name = "__import_" + uuid.uuid4().hex[:14]
            staging = quote_table(options.schema, temp_name)
            definitions = []
            for m in selected:
                dtype = m.data_type
                definitions.append(f"{quote_identifier(m.target_name)} {dtype} NULL")
            if key:
                definitions.append(f"UNIQUE KEY `uq_csv_import_key` ({quote_identifier(key)})")
            ddl = f"CREATE TABLE {staging} ({', '.join(definitions)}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
            qualified = staging
        else:
            qualified = quote_table(options.schema, options.table)
            if options.mode == "replace":
                with conn.cursor() as cur:
                    cur.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s", (options.schema, options.table))
                    engine_row = cur.fetchone()
                    if not engine_row or str(engine_row[0]).upper() != "INNODB":
                        raise ValueError("Replace All อนุญาตเฉพาะ Table แบบ InnoDB เพื่อให้สามารถ Rollback ได้")
            real_columns = list_columns(conn, options.schema, options.table)
            target_lookup = {r["name"].casefold(): r["name"] for r in real_columns}
            for m in selected:
                original = target_lookup.get(m.target_name.casefold())
                if original is None:
                    raise ValueError(f"ไม่พบคอลัมน์ {m.target_name} ใน Table {options.table}")
                m.target_name = original
            selected_names = {m.target_name.casefold() for m in selected}
            missing_required = [
                col["name"] for col in real_columns
                if col["name"].casefold() not in selected_names
                and not col["nullable"] and col["default"] is None
                and "auto_increment" not in col["extra"].lower()
                and "generated" not in col["extra"].lower()
            ]
            if missing_required:
                raise ValueError("ไฟล์ขาดคอลัมน์ที่ Table จำเป็นต้องมี: " + ", ".join(missing_required[:8]))
            if options.mode == "upsert":
                key_columns, index_count = unique_key_columns(conn, options.schema, options.table)
                if index_count != 1 or not key_columns:
                    raise ValueError("Upsert ในเวอร์ชันนี้รองรับ Table ที่มี UNIQUE / PRIMARY KEY แบบคอลัมน์เดียว เพียง 1 ดัชนี")
                if not key or key.casefold() not in {k.casefold() for k in key_columns}:
                    raise ValueError("โปรดเลือก Unique Key ที่มีอยู่จริงใน Table")
                key = next(k for k in key_columns if k.casefold() == key.casefold())
                if key.casefold() not in selected_names:
                    raise ValueError("CSV ต้องมีคอลัมน์ที่จับคู่กับ Unique Key")
        cols = [m.target_name for m in selected]
        alias_supported = _server_supports_alias(conn)
        if options.mode == "replace":
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {qualified}")
            # Transaction remains open until every CSV row has been written.
        batch: list[list[str]] = []
        batch_bytes = 0

        def write_batch() -> None:
            nonlocal batch, batch_bytes, committed
            if not batch:
                return
            params = [cell for row in batch for cell in row]
            sql = _build_insert_sql(qualified, cols, len(batch), options.mode, key, alias_supported)
            with conn.cursor() as cur:
                cur.execute(sql, params)
            if options.mode in ("append", "upsert", "create"):
                conn.commit()
                committed = processed
            batch = []
            batch_bytes = 0
            if progress:
                try:
                    bytes_seen = min(total_bytes, f.buffer.tell())
                except Exception:
                    bytes_seen = 0
                progress(min(99, round(bytes_seen / total_bytes * 100)), processed, f"ประมวลผลแล้ว {processed:,} แถว")

        for row in reader:
            if is_cancelled and is_cancelled():
                raise ImportCancelled("ผู้ใช้ยกเลิกการนำเข้า")
            if not row or all(value == "" for value in row):
                blank_count += 1
                continue
            if len(row) > len(headers):
                raise ValueError(f"แถว CSV ที่บรรทัด {reader.line_num} มี {len(row)} คอลัมน์ เกิน Header {len(headers)} คอลัมน์")
            if len(row) < len(headers):
                row.extend([""] * (len(headers) - len(row)))
            cooked: list[str] = []
            for m in selected:
                value = row[m.source_index]
                if "\x00" in value:
                    raise ValueError(f"พบ NUL ที่แถว {reader.line_num} คอลัมน์ {m.source_name}")
                cooked.append(value)
                batch_bytes += len(value.encode("utf-8")) + 16
            batch.append(cooked)
            processed += 1
            if len(batch) >= 400 or batch_bytes >= 1024 * 1024:
                write_batch()
        write_batch()
        if is_cancelled and is_cancelled():
            raise ImportCancelled("ผู้ใช้ยกเลิกการนำเข้า")
        if options.mode == "replace":
            conn.commit()
            committed = processed
        if options.mode == "create":
            # MySQL's RENAME TABLE is atomic for this one table; avoids partial final table.
            with conn.cursor() as cur:
                cur.execute(f"RENAME TABLE {qualified} TO {quote_table(options.schema, options.table)}")
            conn.commit()
            temp_name = None
        if progress:
            progress(100, processed, "นำเข้าสำเร็จ")
        return ImportResult(processed, f"{options.schema}.{options.table}", blank_count, options.mode, "สำเร็จ")
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        if options.mode in ("append", "upsert") and committed > 0:
            raise PartialImportError(exc, committed) from exc
        raise
    finally:
        f.close()
        if conn is not None:
            if temp_name is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"DROP TABLE IF EXISTS {quote_table(options.schema, temp_name)}")
                    conn.commit()
                except Exception:
                    pass
            conn.close()
