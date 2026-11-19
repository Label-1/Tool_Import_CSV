# UX Contract — CSV Import Studio v6 Multi-Database Space Edition

## Unchanged domain workflow
1. Select CSV/TXT from disk. Preview up to first 20 records. Stream-count all nonempty data records, excluding header and blank records.
2. Enter or choose Schema and Table. Choose Create, Append, Upsert or Replace. Creating a new Schema remains optional only with Create.
3. Connect to MySQL using host, port, username, password; fetch schemas and matching destination tables/columns.
4. Choose target Data Type per source column when creating a new Table. Existing-table Data Types remain read-only, from MySQL.
5. Validate and confirm destination. Replace requires typing REPLACE. Import on worker with progress, cancel, and result/error feedback.
6. Source CSV values are never cleaned or changed (including leading zeros, apostrophes, Thai strings).

## Updated presentation and target-name editing
- The right workspace is preview-first; the preview table grows to fill remaining height.
- The user can increase/decrease preview font via A+/A− and open a larger floating preview window. It shows the same first 20 rows with independent horizontal/vertical scrollbars and no writes.
- The `Column Mapping` table's **target column name is inline editable on a single click**, with Enter, Tab or focus-out to commit; Escape cancels. Double click remains supported.
- The Preview header shows target display names, with a dedicated `แก้ชื่อคอลัมน์` shortcut to the mapping editor; double click on a preview column header also opens its target-name editor.
- A rename only updates `ColumnMapping.target_name`; it is validated as a MySQL identifier; duplicates are rejected. For Append/Upsert/Replace, the name must match an existing destination column. No rename operation is performed on the local CSV or the existing table schema.
- Mapping changes are passed to `importer_core.py` unchanged; CREATE TABLE and INSERT use the new destination name, while CSV binding continues using the original source index and header.

## Canonical UI ownership
| Capability | Owner | Variants |
| --- | --- | --- |
| Tabular data | Native ttk.Treeview | source preview; target mapping; full-size preview |
| Select | Native ttk.Combobox | file encoding / separator; Schema/Table / mode; per-column Data Type |
| Inline target edit | Native tk.Entry inside ttk.Treeview | one-click target rename; commit/cancel handling |
| Form | tk.Entry / native ttk.Combobox | CSV path, Schema, Table, MySQL connection |
| Scrollbars | ttk.Scrollbar styles | sidebar / table x/y / enlarged preview |
| Import lifecycle | `importer_core.py` | Create / Append / Upsert / Replace, unchanged SQL |

## States and recovery
- Demo status explicitly indicates no MySQL connection and cannot perform import.
- Empty source has a prompt; count failure is shown in status and can be retried by re-reading file.
- Invalid target name (empty/duplicate/incompatible) shows an error and retains the prior mapping.
- Imported data progress stays in the persistent footer; duplicate import is blocked; cancellation asks worker to stop.
- Database writes are only initiated by the original confirmed import action.
- The full-screen preview is not modal and can be closed without affecting mappings.

## Locale and accessibility
Thai UI with recognized English data terms. Native keyboard focus remains operable and data is not communicated only by color. Tkinter is native Windows desktop, so web-only browser contracts are not applicable.

## Verification scope
22 core tests and 11 GUI smoke/regression tests cover Demo display, select, mapping, column rename, CSV unchanged, renaming into actual SQL creation, invalid names, and big preview. Tested with Xvfb in Linux; Windows UI and a real MySQL server still require environment-specific confirmation.

## v6 database connector contract
- The user selects `MySQL`, `PostgreSQL`, `SQLite` or `MongoDB`. Backend selection invalidates the old connection and stale metadata.
- MySQL v5 logic is delegated unchanged to `importer_core.py`; other connectors are in `database_backends.py`.
- SQLite selects a local .db file, uses main, and can create its file on Test Connection; PostgreSQL needs an existing connection Database and optionally creates a Schema; MongoDB uses Database/Collection with lazy DB creation.
- Create, Append, Upsert, Replace remain available. The destructive action requires explicit typed confirmation; server-specific transactional or staging semantics are documented in README.
- Source CSV is immutable; changing data types triggers destination-side conversions only when expressly selected.
- MongoDB stores raw strings by default and allows adding new fields to existing collections; SQL existing-table schema matching remains required.
