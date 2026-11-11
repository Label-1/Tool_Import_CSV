# CSV Import Studio v5 — Space Edition · Design Context

## Product and visual thesis
A desktop mission-control workspace for Thai-speaking staff who import cleaned CSV files into MySQL. The **data preview is the primary instrument panel**, not a decorative chart. A dark orbital background, cyan telemetry, and violet actions communicate data moving toward a database. No workflow steps, SQL semantics, or source CSV values are changed for the theme.

## Runtime token owner
**Model B:** the Python `app.py` top-level color constants and `set_theme()` are canonical, with this DESIGN.md documenting them. There is no CSS or web framework. All native Tkinter widgets consume the shared tokens through `label`, `make_button`, `make_entry`, `card`, `section`, and ttk styles. Original decorative assets (`assets/space_*.png`) are authored by `generate_assets.py`; Tkinter loads them using its built-in PNG support without any additional image dependency at runtime.

## Palette
- `BG #080E24`: cosmos canvas for workspace
- `NAVY #090D27`: masthead and full-preview secondary window
- `WHITE #121C3A`: cards and data rows (legacy variable name; semantically *panel*)
- `INPUT_BG #1B2950`: text-entry and select fields
- `HEADING_BG #253461`: data-table column headers
- `STRIPE #19254A`: alternating table rows
- `INK #F2F5FF`: primary foreground
- `MUTED #B0BDE0`: secondary foreground
- `BORDER #354477`: panel/field outlines
- `PRIMARY #925DFF`: main import action and orbital ring
- `PRIMARY_DARK #CCB7FF`: accessible lilac accents and destination labels
- `CYAN #6EDAFB`: counters and active states
- `GREEN #66E8C1`: positive status; `RED #FF99B2`: validation/errors

## Typography and layout
- Windows native Segoe UI, with platform Thai fallbacks; no distributed font dependencies.
- Main title 18–20pt; tab/toolbar 10–11pt; data rows 11pt (user-adjustable 9–15pt); mapping rows 10pt.
- A 310–337px scrollable left workflow column and an independently resizable right workspace. Controls appear in the immutable order: local CSV → Schema/Table → MySQL connection.
- Right workspace: slim header, metrics, destination, tabs, **large vertically-expanding data preview**, persistent import footer. A pop-out read-only preview uses most of the screen when needed; it has internal horizontal/vertical scrolling and zoom buttons.
- Text-entry fields are high contrast; mapping target name column opens an inline editing field with a single click. Data Type opens an inline native combobox. Source values remain read-only.

## Signature
Original starfield/planet header and an orbital route `CSV → SQL` are atmospheric context for a practical data operation. Space illustration stays out of the grid. Content is never placed on a decorative gradient where it compromises readability.

## Interaction and safety
- Main action purple; active tabs cyan; selected table row violet; card panels subdued dark.
- Real operations: progress bar. No continuous ambient animation; reduced motion is naturally respected.
- Keyboard: native tab focus, Enter/Tab commits column rename, Escape cancels, combobox keyboard selection and Escape support.
- Column names: changes update target mapping only and are validated for duplicates and MySQL column compatibility in existing-table modes. Source names and CSV data remain untouched. Preview column headers reflect target display names.
- Existing data operations retain confirmations: Create/Append/Upsert/Replace and typed confirmation for Replace.

## Scope boundary
This is a native Tkinter application, not a browser or Electron UI. Browser ARIA semantics, CSS scrollbar settings, and page URLs do not apply. Native widget controls are the canonical implementations for table, form, select, and progress.
