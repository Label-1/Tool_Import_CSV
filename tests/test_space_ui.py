"""GUI behavior regressions for the space UI (requires a window system)."""
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import ImportStudio
from importer_core import run_import
from test_importer_core import FakeConn


class SpaceUIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = ImportStudio(demo=True)
        self.root.geometry('1280x850+0+0')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if self.root.row_count == 32:
                break
            time.sleep(0.02)
        self.assertEqual(self.root.row_count, 32)

    def tearDown(self):
        try:
            for after_id in self.root.tk.call('after', 'info'):
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
            self.root.destroy()
        except tk.TclError:
            pass

    def test_single_click_target_cell_opens_inline_entry(self):
        self.root._switch_tab('mapping')
        self.root.update()
        x,y,w,h=self.root.mapping_tree.bbox('0','#3')
        event=type('Event',(),{'x':x+w//2,'y':y+h//2})()
        self.root._mapping_click(event)
        self.assertIsInstance(self.root._active_editor, tk.Entry)
        self.root.update()
        edit=self.root._active_editor
        edit.delete(0,'end')
        edit.insert(0,'customer_ref')
        edit.event_generate('<Return>')
        self.root.update()
        self.assertEqual(self.root.mappings[0].target_name,'customer_ref')
        self.assertEqual(self.root.mappings[0].source_name,'REF_ID')
        self.assertEqual(self.root.preview.rows[0][0],'0000000000001')
        self.assertEqual(self.root.preview_tree.heading('col_0')['text'],'customer_ref')

    def test_rename_from_preview_button_gives_an_immediate_editor(self):
        self.root._jump_to_column_names()
        self.root.update()
        time.sleep(0.11)
        self.root.update()
        self.assertEqual(self.root.active_tab, 'mapping')
        self.assertIsInstance(self.root._active_editor, tk.Entry)

    def test_duplicate_target_names_rejected(self):
        self.root._switch_tab('mapping')
        self.root.update()
        original=self.root.mappings[0].target_name
        self.root._edit_target(0)
        self.root.update()
        edit=self.root._active_editor
        edit.delete(0,'end')
        edit.insert(0,self.root.mappings[1].target_name)
        with patch('app.messagebox.showerror') as show_error:
            edit.event_generate('<Return>')
            self.root.update()
        self.assertTrue(show_error.called)
        self.assertEqual(self.root.mappings[0].target_name,original)

    def test_escape_cancels_target_rename(self):
        self.root._switch_tab('mapping')
        self.root.update()
        old=self.root.mappings[0].target_name
        self.root._edit_target(0)
        self.root.update()
        edit=self.root._active_editor
        edit.delete(0,'end')
        edit.insert(0,'discard_this')
        edit.event_generate('<Escape>')
        self.root.update()
        self.assertEqual(self.root.mappings[0].target_name,old)
        self.assertIsNone(self.root._active_editor)

    def test_focus_out_commits_target_rename(self):
        self.root._switch_tab('mapping')
        self.root.update()
        self.root._edit_target(0)
        self.root.update()
        edit=self.root._active_editor
        edit.delete(0,'end')
        edit.insert(0,'saved_on_blur')
        edit.event_generate('<FocusOut>')
        self.root.update()
        self.assertEqual(self.root.mappings[0].target_name,'saved_on_blur')

    def test_large_preview_uses_all_source_rows_sample_without_value_changes(self):
        self.root._open_large_preview()
        self.root.update()
        self.assertTrue(self.root.preview_popup.winfo_exists())
        self.assertEqual(len(self.root.popup_tree.get_children()),20)
        oldsize=self.root.preview_font_size
        self.root._change_preview_zoom(1)
        self.assertEqual(self.root.preview_font_size,oldsize+1)
        self.root.preview_popup.destroy()
        self.root.update()

    def test_column_rename_flows_into_actual_create_sql(self):
        self.root._switch_tab('mapping')
        self.root.update()
        self.root._edit_target(0)
        self.root.update()
        edit=self.root._active_editor
        edit.delete(0,'end')
        edit.insert(0,'new_ref_code')
        edit.event_generate('<Return>')
        self.root.update()
        self.root.connected=True
        self.root.schemas=['testdb']
        self.root.schema_var.set('testdb')
        self.root.table_var.set('targettable')
        opts=self.root._build_options()
        self.assertEqual(opts.expected_headers[0],'REF_ID')
        self.assertEqual(opts.mappings[0].target_name,'new_ref_code')
        db=FakeConn(table_exists=False)
        with patch('importer_core.connect',return_value=db):
            result=run_import(opts)
        sql='\n'.join(statement for statement, _ in db.statements)
        self.assertIn('`new_ref_code` TEXT',sql)
        self.assertIn('(`new_ref_code`,',sql)
        self.assertEqual(result.processed,32)
        insert_params=[params for sql_stmt,params in db.statements if sql_stmt.startswith('INSERT')]
        self.assertTrue(insert_params)
        self.assertEqual(insert_params[0][0],'0000000000001')


if __name__=='__main__':
    unittest.main()
