# main.py
import tkinter as tk
from app_gui import GcodeViewerApp

if __name__ == "__main__":
    root = tk.Tk()
    app = GcodeViewerApp(root)
    root.mainloop()