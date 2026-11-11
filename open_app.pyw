"""No-console Windows entry point for CSV Import Studio."""
from pathlib import Path
import os
import traceback

os.chdir(Path(__file__).resolve().parent)
try:
    from app import ImportStudio
    ImportStudio(demo=False).mainloop()
except Exception:
    Path('startup_error.log').write_text(traceback.format_exc(), encoding='utf-8')
    try:
        from tkinter import messagebox
        messagebox.showerror('CSV Import Studio',
                             'Unable to start. See startup_error.log in this folder.')
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,
                'Unable to start. See startup_error.log in this folder.',
                'CSV Import Studio', 0x10)
        except Exception:
            pass
