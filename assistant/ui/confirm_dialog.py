"""Modal confirmation dialog for L3 (CONFIRM) actions (Section 8.2 & 13)."""

from __future__ import annotations

import sys
from typing import Optional


def request_confirmation(
    action_title: str,
    tool_name: str,
    target_resource: str,
    details: str,
    diff_text: Optional[str] = None,
    backup_path: Optional[str] = None,
    rollback_cmd: Optional[str] = None,
    parent_window: Optional[object] = None,
) -> bool:
    """Request explicit user confirmation for an L3 action via Tk modal dialog or terminal fallback.
    
    Returns True only if user explicitly clicks 'Setuju' or types 'yes'.
    """
    # Try GUI modal dialog first if Tkinter is available and display exists
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext

        root = parent_window if parent_window is not None else tk.Tk()
        if parent_window is None:
            root.withdraw()

        dialog = tk.Toplevel(root)
        dialog.title("Konfirmasi Tindakan Sistem (L3)")
        dialog.geometry("620x540")
        dialog.configure(bg="#1e1e2e")
        dialog.resizable(True, True)
        dialog.attributes("-topmost", True)
        dialog.grab_set()  # Make modal

        user_confirmed = [False]

        # Header Frame
        header_frame = tk.Frame(dialog, bg="#313244", padx=16, pady=12)
        header_frame.pack(fill=tk.X)

        warn_label = tk.Label(
            header_frame,
            text="⚠️  PERSETUJUAN OPERASI SISTEM (L3 - CONFIRM)",
            font=("Segoe UI", 11, "bold"),
            fg="#f9e2af",
            bg="#313244",
        )
        warn_label.pack(anchor="w")

        title_label = tk.Label(
            header_frame,
            text=action_title,
            font=("Segoe UI", 12, "bold"),
            fg="#cdd6f4",
            bg="#313244",
        )
        title_label.pack(anchor="w", pady=(4, 0))

        # Content Frame
        content_frame = tk.Frame(dialog, bg="#1e1e2e", padx=16, pady=12)
        content_frame.pack(fill=tk.BOTH, expand=True)

        meta_text = f"Tool: {tool_name}\nTarget: {target_resource}\n\nDetail:\n{details}"
        meta_label = tk.Label(
            content_frame,
            text=meta_text,
            font=("Segoe UI", 9),
            fg="#a6adc8",
            bg="#1e1e2e",
            justify="left",
            anchor="w",
        )
        meta_label.pack(fill=tk.X, pady=(0, 8))

        if diff_text:
            diff_label = tk.Label(
                content_frame,
                text="Perubahan / Diff File:",
                font=("Segoe UI", 9, "bold"),
                fg="#89b4fa",
                bg="#1e1e2e",
            )
            diff_label.pack(anchor="w")

            diff_box = scrolledtext.ScrolledText(
                content_frame,
                height=10,
                bg="#11111b",
                fg="#a6e3a1",
                insertbackground="#cdd6f4",
                font=("Consolas", 9),
                wrap=tk.WORD,
            )
            diff_box.insert(tk.END, diff_text)
            diff_box.configure(state="disabled")
            diff_box.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

        if backup_path or rollback_cmd:
            rollback_frame = tk.Frame(content_frame, bg="#181825", padx=8, pady=6)
            rollback_frame.pack(fill=tk.X, pady=(0, 8))
            rb_info = []
            if backup_path:
                rb_info.append(f"Backup tersimpan di: {backup_path}")
            if rollback_cmd:
                rb_info.append(f"Cara rollback: {rollback_cmd}")
            rb_label = tk.Label(
                rollback_frame,
                text="\n".join(rb_info),
                font=("Segoe UI", 8),
                fg="#f38ba8",
                bg="#181825",
                justify="left",
            )
            rb_label.pack(anchor="w")

        # Action Buttons Frame
        btn_frame = tk.Frame(dialog, bg="#1e1e2e", padx=16, pady=12)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        def on_confirm():
            user_confirmed[0] = True
            dialog.destroy()

        def on_cancel():
            user_confirmed[0] = False
            dialog.destroy()

        # Reject / Cancel Button (Left, default focus for safety)
        btn_cancel = tk.Button(
            btn_frame,
            text="Tolak (Batal) [Esc]",
            command=on_cancel,
            bg="#313244",
            fg="#cdd6f4",
            activebackground="#45475a",
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=6,
            relief=tk.FLAT,
        )
        btn_cancel.pack(side=tk.LEFT)

        # Confirm Button (Right, green accent)
        btn_confirm = tk.Button(
            btn_frame,
            text="Setuju & Jalankan Tindakan",
            command=on_confirm,
            bg="#a6e3a1",
            fg="#11111b",
            activebackground="#94e2d5",
            activeforeground="#11111b",
            font=("Segoe UI", 10, "bold"),
            padx=18,
            pady=6,
            relief=tk.FLAT,
        )
        btn_confirm.pack(side=tk.RIGHT)

        dialog.bind("<Escape>", lambda e: on_cancel())
        btn_cancel.focus_set()

        dialog.wait_window()

        if parent_window is None:
            root.destroy()

        return user_confirmed[0]

    except Exception:
        # Fallback to interactive CLI terminal prompt if GUI fails/absent
        print("\n" + "=" * 65, file=sys.stderr)
        print(" [KONFIRMASI TINDAKAN SISTEM - TINGKAT RISIKO L3]", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        print(f" Tindakan : {action_title}", file=sys.stderr)
        print(f" Tool     : {tool_name}", file=sys.stderr)
        print(f" Target   : {target_resource}", file=sys.stderr)
        print(f" Detail   : {details}", file=sys.stderr)
        if diff_text:
            print("-" * 65, file=sys.stderr)
            print(diff_text, file=sys.stderr)
        if backup_path:
            print(f" Backup   : {backup_path}", file=sys.stderr)
        if rollback_cmd:
            print(f" Rollback : {rollback_cmd}", file=sys.stderr)
        print("=" * 65, file=sys.stderr)

        try:
            choice = input(" Ketik 'ya' / 'yes' untuk menyetujui, Enter untuk membatalkan: ").strip().lower()
            return choice in ("ya", "yes", "y")
        except (EOFError, KeyboardInterrupt):
            return False
