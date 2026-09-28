"""Tkinter GUI fixture for Phase 10A UIA tests.

Creates a minimal but complete desktop window with:
  - Standard button (for InvokePattern testing)
  - Edit/text input (for ValuePattern testing)
  - Password field (to verify L0/REDACT behavior)
  - Checkbox (for TogglePattern)
  - Static text label
  - AutomationId-bearing controls (for AutomationId search)

Run standalone: python tests/fixtures/test_gui_window.py
Outputs HWND to stdout then keeps window alive until keypress or timeout.
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
import ctypes


def create_fixture_window(ready_event: threading.Event = None) -> tk.Tk:
    root = tk.Tk()
    root.title("Jarvis UIA Test Fixture")
    root.geometry("400x320")

    # Set accessibility-friendly widget names where possible
    # Note: Tkinter uses WM_NAME as window Name; child controls get default names

    frame = tk.Frame(root, padx=12, pady=12)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(frame, text="Jarvis Phase 10A Test Window", font=("Arial", 12, "bold")).pack(anchor=tk.W)
    tk.Label(frame, text="This is a static label.").pack(anchor=tk.W, pady=(4, 0))

    # Search input (non-sensitive)
    tk.Label(frame, text="Search Query:").pack(anchor=tk.W, pady=(8, 0))
    search_entry = tk.Entry(frame, width=30)
    search_entry.pack(anchor=tk.W)

    # Password field (sensitive - must be redacted)
    tk.Label(frame, text="Password (should be REDACTED):").pack(anchor=tk.W, pady=(8, 0))
    password_entry = tk.Entry(frame, show="*", width=30)
    password_entry.pack(anchor=tk.W)
    password_entry.insert(0, "super_secret_password_123")

    # Checkbox
    chk_var = tk.BooleanVar()
    chk = tk.Checkbutton(frame, text="Enable Feature", variable=chk_var)
    chk.pack(anchor=tk.W, pady=(8, 0))

    # Buttons
    btn_frame = tk.Frame(frame)
    btn_frame.pack(anchor=tk.W, pady=(12, 0))
    ok_btn = tk.Button(btn_frame, text="OK", width=8)
    ok_btn.pack(side=tk.LEFT, padx=(0, 4))
    cancel_btn = tk.Button(btn_frame, text="Cancel", width=8)
    cancel_btn.pack(side=tk.LEFT, padx=(0, 4))
    del_btn = tk.Button(btn_frame, text="Delete Account", width=14, fg="red")
    del_btn.pack(side=tk.LEFT)

    if ready_event is not None:
        root.after(200, ready_event.set)

    return root


if __name__ == "__main__":
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    ready = threading.Event()
    root = create_fixture_window(ready)

    # Print HWND for test harness
    def print_hwnd():
        ready.wait(timeout=5.0)
        time.sleep(0.1)
        hwnd = ctypes.windll.user32.FindWindowW(None, "Jarvis UIA Test Fixture")
        print(f"HWND:{hwnd}", flush=True)

    t = threading.Thread(target=print_hwnd, daemon=True)
    t.start()

    root.after(int(timeout * 1000), root.destroy)
    root.mainloop()
