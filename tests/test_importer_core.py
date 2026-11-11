import os
import tempfile
import unittest
from pathlib import Path

from importer_core import (
    CSVSpec, ColumnMapping, DbSettings, ImportOptions,
    _build_insert_sql, _check_config, preview_csv, count_csv_rows, ImportCancelled,
    quote_identifier, quote_table, validate_simple_identifier,
)


class ParsingTests(unittest.TestCase):
    def write_csv(self, name, contents, encoding="utf-8"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / name
        path.write_text(contents, encoding=encoding, newline="")
        return path

    def test_leading_zeros_and_apostrophe_preserved(self):
        path = self.write_csv("records.csv", "ID_CARD,ชื่อ\n0000123456789,ตัวอย่าง\n'0000123456789,ทดสอบ\n")
        result = preview_csv(CSVSpec(str(path)))
        self.assertEqual(result.rows[0][0], "0000123456789")
        self.assertEqual(result.rows[1][0], "'0000123456789")
        self.assertEqual(result.rows[0][1], "ตัวอย่าง")

    def test_cp874_thai(self):
        path = self.write_csv("thai.csv", "เลขบัตร,ชื่อ\n00001,ภาษาไทย\n", "cp874")
        result = preview_csv(CSVSpec(str(path)))
        self.assertEqual(result.encoding, "cp874")
        self.assertEqual(result.headers, ["เลขบัตร", "ชื่อ"])

    def test_bom_quoted_comma(self):
        path = self.write_csv("utf8.csv", 'id,note\n001,"text, with comma"\n', "utf-8-sig")
        result = preview_csv(CSVSpec(str(path)))
        self.assertEqual(result.headers[0], "id")
        self.assertEqual(result.rows[0], ["001", "text, with comma"])

    def test_semicolon_and_duplicate_headers(self):
        path = self.write_csv("semicolon.csv", "a;a;เลข\n001;test;03\n")
        result = preview_csv(CSVSpec(str(path)))
        self.assertEqual(result.delimiter, ";")
        self.assertEqual(result.headers, ["a", "a__2", "เลข"])

    def test_count_rows_excludes_headers_and_blank_rows(self):
        path = self.write_csv('count.csv', 'id,name\n1,AA\n\n2,BB\n,\n3,CC\n')
        pv = preview_csv(CSVSpec(str(path)))
        stats = count_csv_rows(CSVSpec(str(path)))
        self.assertEqual(len(pv.rows), 3)
        self.assertEqual(stats.data_rows, 3)
        self.assertEqual(stats.blank_rows, 2)

    def test_count_csv_records_not_physical_lines(self):
        path = self.write_csv('multiline.csv', 'id,note\n1,"line one\nline two"\n2,"ok"\n')
        stats = count_csv_rows(CSVSpec(str(path)))
        self.assertEqual(stats.data_rows, 2)
        self.assertEqual(stats.blank_rows, 0)

    def test_count_beyond_20_preview_limit(self):
        path = self.write_csv('large.csv', 'id,note\n' + ''.join(f'{i},record {i}\n' for i in range(100)))
        self.assertEqual(len(preview_csv(CSVSpec(str(path))).rows), 20)
        self.assertEqual(count_csv_rows(CSVSpec(str(path))).data_rows, 100)

    def test_zero_data_rows(self):
        path = self.write_csv('empty_rows.csv', 'id,note\n\n,\n')
        self.assertEqual(count_csv_rows(CSVSpec(str(path))).data_rows, 0)

    def test_count_invalid_row_after_preview_sample(self):
        path = self.write_csv('bad.csv', 'id,note\n' + ('1,ok\n' * 25) + '2,bad,extra\n')
        self.assertEqual(len(preview_csv(CSVSpec(str(path))).rows), 20)
        with self.assertRaisesRegex(ValueError, 'คอลัมน์'):
            count_csv_rows(CSVSpec(str(path)))

    def test_count_cancellation(self):
        path = self.write_csv('cancel.csv', 'id,name\n1,x\n')
        with self.assertRaises(ImportCancelled):
            count_csv_rows(CSVSpec(str(path)), is_cancelled=lambda: True)

    def test_invalid_extra_column(self):
        path = self.write_csv("invalid.csv", "id,name\n1,A,extra\n")
        with self.assertRaisesRegex(ValueError, "คอลัมน์"):
            preview_csv(CSVSpec(str(path)))


class SQLTests(unittest.TestCase):
    def test_sql_quoted_thai(self):
        self.assertEqual(quote_identifier("เลขบัตรประชาชน"), "`เลขบัตรประชาชน`")
        self.assertEqual(quote_table("label_idcard_mobile", "rep_mobile_6908"), "`label_idcard_mobile`.`rep_mobile_6908`")

    def test_identifier_rejects_injection(self):
        with self.assertRaises(ValueError):
            validate_simple_identifier("data;DROP DATABASE data", "Schema")
        with self.assertRaises(ValueError):
            quote_identifier("id` DROP")

    def test_create_type_validation(self):
        opts = ImportOptions(CSVSpec("test.csv"), DbSettings("localhost", 3306, "test", ""),
                             "safe_db", "safe_table", "create",
                             [ColumnMapping(0, "id", "id", "REAL NOT NULL")])
        with self.assertRaisesRegex(ValueError, "ประเภทข้อมูล"):
            _check_config(opts)

    def test_key_must_have_indexable_type(self):
        opts = ImportOptions(CSVSpec("test.csv"), DbSettings("localhost", 3306, "test", ""),
                             "safe_db", "safe_table", "create",
                             [ColumnMapping(0, "id", "id", "TEXT")], unique_key="id")
        with self.assertRaisesRegex(ValueError, "Unique Key"):
            _check_config(opts)

    def test_type_selectable_from_allowlist(self):
        from importer_core import TYPES
        self.assertIn("DATETIME", TYPES)
        self.assertIn("DECIMAL(18,2)", TYPES)
        self.assertIn("VARCHAR(100)", TYPES)
        opts = ImportOptions(CSVSpec("test.csv"), DbSettings("localhost", 3306, "test", ""),
                             "safe_db", "safe_table", "create",
                             [ColumnMapping(0, "price", "price", "DECIMAL(18,2)")])
        self.assertEqual(_check_config(opts)[0].data_type, "DECIMAL(18,2)")

    def test_upsert_uses_new_row_alias(self):
        query = _build_insert_sql("`db`.`tbl`", ["id", "ชื่อ"], 2, "upsert", "id", True)
        self.assertIn("AS _incoming ON DUPLICATE KEY UPDATE", query)
        self.assertIn("`ชื่อ` = _incoming.`ชื่อ`", query)
        self.assertEqual(query.count("%s"), 4)

    def test_varchar_column_mapping_still_valid_for_append(self):
        opts = ImportOptions(CSVSpec("test.csv"), DbSettings("localhost", 3306, "test", ""),
                             "safe_db", "safe_table", "append",
                             [ColumnMapping(0, "id", "id", "VARCHAR(13)")])
        self.assertEqual(len(_check_config(opts)), 1)


if __name__ == "__main__":
    unittest.main()


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.out = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        if sql.startswith("SELECT @@SESSION.sql_mode"):
            self.out = [("STRICT_TRANS_TABLES",)]
        elif sql.startswith("SELECT SCHEMA_NAME"):
            self.out = [("testdb",)]
        elif sql.startswith("SELECT TABLE_NAME"):
            self.out = [("testtable",)] if self.conn.table_exists else []
        elif sql.startswith("SELECT ENGINE"):
            self.out = [("InnoDB",)]
        elif sql.startswith("SHOW FULL COLUMNS"):
            self.out = [
                ("ID", "varchar(255)", None, "NO", "PRI", None, "", "", ""),
                ("NAME", "text", None, "YES", "", None, "", "", ""),
            ]
        elif sql.startswith("SHOW INDEX"):
            self.out = [("testtable", 0, "PRIMARY", 1, "ID")]
        else:
            self.out = []
        return 1

    def fetchone(self):
        return self.out[0] if self.out else None

    def fetchall(self):
        return self.out


class FakeConn:
    def __init__(self, table_exists):
        self.table_exists = table_exists
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def get_server_info(self):
        return "8.4.2"

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class ImportFlowTests(unittest.TestCase):
    def write_file(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "flow.csv"
        path.write_text(data, encoding="utf-8")
        return path

    def execute_fake(self, mode, csv_text, mappings, key=""):
        from unittest.mock import patch
        from importer_core import run_import
        db = FakeConn(mode != "create")
        path = self.write_file(csv_text)
        pv = preview_csv(CSVSpec(str(path))) if csv_text.count("\n") > 1 else None
        opts = ImportOptions(
            CSVSpec(str(path)), DbSettings("localhost", 3306, "test", ""),
            "testdb", "testtable", mode, mappings,
            unique_key=key,
            expected_headers=pv.headers if pv else None,
        )
        with patch("importer_core.connect", return_value=db):
            out = run_import(opts)
        return db, out

    def test_create_staging_preserves_exact_csv_text(self):
        maps = [ColumnMapping(0, "ID", "ID", "VARCHAR(255)"), ColumnMapping(1, "NAME", "NAME")]
        db, result = self.execute_fake("create", "ID,NAME\n00001,ตัวอย่าง\n", maps, "ID")
        self.assertEqual(result.processed, 1)
        sql_text = "\n".join(sql for sql, _ in db.statements)
        self.assertIn("CREATE TABLE `testdb`.`__import_", sql_text)
        self.assertIn("RENAME TABLE", sql_text)
        insert = next(params for sql, params in db.statements if sql.startswith("INSERT"))
        self.assertEqual(insert, ["00001", "ตัวอย่าง"])

    def test_no_value_cleaning_or_added_apostrophe(self):
        maps = [ColumnMapping(0, "ID", "ID", "VARCHAR(255)"), ColumnMapping(1, "NAME", "NAME")]
        db, result = self.execute_fake("create", "ID,NAME\n00001,ภาษาไทย\n'00200,ทดสอบ\n", maps)
        insert_params = [params for sql, params in db.statements if sql.startswith("INSERT")]
        self.assertEqual(insert_params, [["00001", "ภาษาไทย", "'00200", "ทดสอบ"]])

    def test_upsert_on_key(self):
        maps = [ColumnMapping(0, "ID", "ID"), ColumnMapping(1, "NAME", "NAME")]
        db, result = self.execute_fake("upsert", "ID,NAME\n00001,ทดสอบ\n", maps, "ID")
        self.assertEqual(result.processed, 1)
        self.assertTrue(any("ON DUPLICATE KEY UPDATE" in sql for sql, _ in db.statements))

    def test_replace_delete_and_commit(self):
        maps = [ColumnMapping(0, "ID", "ID"), ColumnMapping(1, "NAME", "NAME")]
        db, result = self.execute_fake("replace", "ID,NAME\n00001,ดี\n", maps)
        self.assertEqual(result.processed, 1)
        self.assertTrue(any(sql.startswith("DELETE FROM") for sql, _ in db.statements))
        self.assertEqual(db.commits, 1)
