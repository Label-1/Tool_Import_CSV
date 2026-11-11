"""Run this GUI smoke suite under a desktop session, e.g. xvfb-run on Linux."""
import unittest
import time
import tkinter as tk
from app import ImportStudio, MODE_LABELS


class ImportStudioVisualSmoke(unittest.TestCase):
    def setUp(self):
        self.root = ImportStudio(demo=True)
        self.root.geometry('1200x780+0+0')
        end = time.monotonic() + 4
        while time.monotonic() < end:
            self.root.update()
            if self.root.row_count is not None:
                break
            time.sleep(0.02)
        self.assertEqual(self.root.row_count, 32)
        self.assertEqual(self.root.stat_columns_var.get(), '6')

    def tearDown(self):
        for after_id in self.root.tk.call('after', 'info'):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        if self.root.winfo_exists():
            self.root.destroy()

    def test_demo_has_live_source_destination_and_readonly_preview(self):
        self.assertEqual(len(self.root.preview.rows), 20)
        self.assertEqual(len(self.root.mappings), 6)
        self.assertIn('label_idcard_mobile', self.root.destination_var.get())
        self.assertIn('rep_mobile_6908', self.root.destination_var.get())
        self.assertFalse(self.root.connected)
        self.assertEqual(self.root.current_mode(), 'create')
        self.root.table_var.set('new_target_table')
        self.root.update()
        self.assertIn('new_target_table', self.root.destination_var.get())

    def test_data_type_inline_dropdown_and_tab_switch(self):
        self.root._switch_tab('mapping')
        self.root.update()
        self.assertEqual(self.root.active_tab, 'mapping')
        self.root._edit_data_type(0, post_dropdown=False)
        editor = self.root._active_editor
        self.assertIsNotNone(editor)
        editor.set('VARCHAR(255)')
        editor.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(self.root.mappings[0].data_type, 'VARCHAR(255)')
        self.root._switch_tab('preview')
        self.assertEqual(self.root.active_tab, 'preview')

    def test_existing_table_modes_keep_existing_type_locked(self):
        append_label = next(k for k, v in MODE_LABELS.items() if v == 'append')
        self.root.mode_var.set(append_label)
        self.root._mode_changed()
        self.assertEqual(self.root.current_mode(), 'append')
        self.assertEqual(self.root.all_text_btn.cget('state'), 'disabled')
        self.root._switch_tab('mapping')
        self.root._edit_data_type(0, post_dropdown=False)
        self.assertIsNone(self.root._active_editor)

    def test_demo_cannot_import_without_database_connection(self):
        with self.assertRaisesRegex(ValueError, 'MySQL'):
            self.root._build_options()


if __name__ == '__main__':
    unittest.main()
