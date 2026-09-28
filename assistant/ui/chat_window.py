"""Jarvis PC Operator Chat Window (Tkinter Dark Mode, Section 13)."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable, Optional

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from assistant.core.orchestrator import orchestrator, Orchestrator
from assistant.ui.reports import save_markdown_report


class ChatWindow:
    """Lightweight, modern dark-mode chat window for Jarvis-lite."""

    THEME = {
        "bg_dark": "#181825",
        "bg_window": "#1e1e2e",
        "bg_card": "#313244",
        "bg_input": "#313244",
        "fg_text": "#cdd6f4",
        "fg_muted": "#a6adc8",
        "accent": "#89b4fa",
        "accent_green": "#a6e3a1",
        "accent_yellow": "#f9e2af",
        "accent_red": "#f38ba8",
        "accent_peach": "#fab387",
    }

    def __init__(
        self,
        orch: Orchestrator | None = None,
        on_hide_callback: Callable[[], None] | None = None,
    ) -> None:
        self.orch = orch or orchestrator
        self.on_hide_callback = on_hide_callback
        self._is_working = False
        self.cancel_event = threading.Event()
        self.last_result: Optional[dict[str, Any]] = None
        self.last_query: str = ""
        self._is_recording_voice: bool = False

        # Initialize root window
        self.root = tk.Tk()
        self.root.title("Jarvis PC Operator")
        self.root.geometry("600x700")
        self.root.minsize(480, 560)
        self.root.configure(bg=self.THEME["bg_window"])

        # Intercept close button to hide to tray
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        # Build UI layout
        self._build_header()
        self._build_quick_actions()
        self._build_chat_area()
        self._build_status_bar()
        self._build_input_area()

        # Keyboard shortcuts
        self.root.bind("<Escape>", lambda e: self.on_cancel_clicked())

        # Welcome message
        self.append_message(
            "Jarvis",
            "Halo! Saya Jarvis, asisten PC lokal Anda.\n"
            "Ketik perintah seperti 'buka youtube', 'cek spek', atau tanya masalah seperti 'kenapa tadi bsod?'.",
            tag="jarvis",
        )

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=self.THEME["bg_dark"], padx=14, pady=10)
        header.pack(fill=tk.X)

        title_frame = tk.Frame(header, bg=self.THEME["bg_dark"])
        title_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.indicator_label = tk.Label(
            title_frame,
            text="●",
            font=("Segoe UI", 14),
            fg=self.THEME["accent_green"],
            bg=self.THEME["bg_dark"],
        )
        self.indicator_label.pack(side=tk.LEFT, padx=(0, 6))

        title = tk.Label(
            title_frame,
            text="JARVIS PC OPERATOR",
            font=("Segoe UI", 11, "bold"),
            fg=self.THEME["fg_text"],
            bg=self.THEME["bg_dark"],
        )
        title.pack(side=tk.LEFT)

        shortcut_hint = tk.Label(
            header,
            text="Ctrl+Shift+J (Sembunyikan)",
            font=("Segoe UI", 9),
            fg=self.THEME["fg_muted"],
            bg=self.THEME["bg_dark"],
        )
        shortcut_hint.pack(side=tk.RIGHT, padx=4)

    def _build_quick_actions(self) -> None:
        quick_frame = tk.Frame(self.root, bg=self.THEME["bg_window"], padx=12, pady=6)
        quick_frame.pack(fill=tk.X)

        actions = [
            ("⚡ Spek Sistem", "cek spesifikasi sistem"),
            ("🩺 Diagnosa BSOD", "kenapa tadi bsod?"),
            ("💾 Disk 100%", "disk gw 100% terus nih"),
            ("🐢 Laptop Lemot", "laptop lemot banget kenapa ya"),
        ]

        for label, prompt in actions:
            btn = tk.Button(
                quick_frame,
                text=label,
                command=lambda p=prompt: self._on_quick_action(p),
                bg=self.THEME["bg_card"],
                fg=self.THEME["fg_text"],
                activebackground=self.THEME["accent"],
                activeforeground=self.THEME["bg_dark"],
                relief=tk.FLAT,
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=2,
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=3)

    def _build_chat_area(self) -> None:
        chat_container = tk.Frame(self.root, bg=self.THEME["bg_window"], padx=12, pady=4)
        chat_container.pack(fill=tk.BOTH, expand=True)

        self.chat_display = scrolledtext.ScrolledText(
            chat_container,
            wrap=tk.WORD,
            bg=self.THEME["bg_dark"],
            fg=self.THEME["fg_text"],
            insertbackground=self.THEME["fg_text"],
            font=("Segoe UI", 10),
            padx=12,
            pady=10,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        # Style tags
        self.chat_display.tag_config(
            "user",
            foreground=self.THEME["accent"],
            font=("Segoe UI", 10, "bold"),
            spacing1=8,
            spacing3=2,
        )
        self.chat_display.tag_config(
            "jarvis",
            foreground=self.THEME["accent_green"],
            font=("Segoe UI", 10, "bold"),
            spacing1=8,
            spacing3=2,
        )
        self.chat_display.tag_config(
            "diagnostics",
            foreground=self.THEME["accent_peach"],
            font=("Segoe UI", 10, "bold"),
            spacing1=8,
            spacing3=2,
        )
        self.chat_display.tag_config(
            "content",
            foreground=self.THEME["fg_text"],
            font=("Segoe UI", 10),
            spacing3=6,
        )
        self.chat_display.tag_config(
            "findings",
            foreground=self.THEME["accent_yellow"],
            font=("Consolas", 9),
            spacing3=6,
        )
        self.chat_display.tag_config(
            "system",
            foreground=self.THEME["fg_muted"],
            font=("Segoe UI", 9, "italic"),
            spacing3=4,
        )

        self.chat_display.configure(state="disabled")

    def _build_status_bar(self) -> None:
        self.status_frame = tk.Frame(self.root, bg=self.THEME["bg_dark"], padx=14, pady=4)
        self.status_frame.pack(fill=tk.X)

        self.status_label = tk.Label(
            self.status_frame,
            text="Status: Siap menerima perintah",
            font=("Segoe UI", 9),
            fg=self.THEME["fg_muted"],
            bg=self.THEME["bg_dark"],
            anchor="w",
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_save_report = tk.Button(
            self.status_frame,
            text="Simpan Laporan (.md)",
            command=self.save_current_report,
            bg=self.THEME["bg_card"],
            fg=self.THEME["accent"],
            activebackground=self.THEME["accent"],
            activeforeground=self.THEME["bg_dark"],
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=1,
            relief=tk.FLAT,
            cursor="hand2",
        )
        self.btn_save_report.pack(side=tk.RIGHT)

    def _build_input_area(self) -> None:
        input_frame = tk.Frame(self.root, bg=self.THEME["bg_window"], padx=12, pady=10)
        input_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.input_entry = tk.Entry(
            input_frame,
            bg=self.THEME["bg_input"],
            fg=self.THEME["fg_text"],
            insertbackground=self.THEME["fg_text"],
            font=("Segoe UI", 11),
            relief=tk.FLAT,
            borderwidth=8,
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self.on_send_clicked())

        self.btn_send = tk.Button(
            input_frame,
            text="Kirim",
            command=self.on_send_clicked,
            bg=self.THEME["accent"],
            fg=self.THEME["bg_dark"],
            activebackground="#b4befe",
            activeforeground=self.THEME["bg_dark"],
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=4,
            relief=tk.FLAT,
            cursor="hand2",
        )
        self.btn_send.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_voice = tk.Button(
            input_frame,
            text="🎤 Suara",
            command=self.on_voice_clicked,
            bg=self.THEME["bg_card"],
            fg=self.THEME["accent_peach"],
            activebackground=self.THEME["accent_peach"],
            activeforeground=self.THEME["bg_dark"],
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=4,
            relief=tk.FLAT,
            cursor="hand2",
        )
        self.btn_voice.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_cancel = tk.Button(
            input_frame,
            text="Batal",
            command=self.on_cancel_clicked,
            bg=self.THEME["bg_card"],
            fg=self.THEME["accent_red"],
            activebackground=self.THEME["accent_red"],
            activeforeground=self.THEME["bg_dark"],
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=4,
            relief=tk.FLAT,
            cursor="hand2",
        )
        self.btn_cancel.pack(side=tk.LEFT)

    def append_message(self, sender: str, text: str, tag: str = "jarvis") -> None:
        """Safely append a message to the chat display."""
        def _do_append():
            self.chat_display.configure(state="normal")
            self.chat_display.insert(tk.END, f"[{sender}]\n", tag)
            self.chat_display.insert(tk.END, f"{text}\n\n", "content")
            self.chat_display.see(tk.END)
            self.chat_display.configure(state="disabled")

        if threading.current_thread() is threading.main_thread():
            _do_append()
        else:
            self.root.after(0, _do_append)

    def update_status(self, text: str, is_working: bool = False) -> None:
        """Update status bar label and header indicator."""
        def _do_update():
            self._is_working = is_working
            self.status_label.config(text=f"Status: {text}")
            if is_working:
                self.indicator_label.config(text="●", fg=self.THEME["accent_yellow"])
            else:
                self.indicator_label.config(text="●", fg=self.THEME["accent_green"])

        if threading.current_thread() is threading.main_thread():
            _do_update()
        else:
            self.root.after(0, _do_update)

    def _on_quick_action(self, prompt: str) -> None:
        if self._is_working:
            return
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, prompt)
        self.on_send_clicked()

    def on_send_clicked(self) -> None:
        if self._is_working:
            return
        query = self.input_entry.get().strip()
        if not query:
            return

        self.input_entry.delete(0, tk.END)
        self.append_message("Anda", query, tag="user")
        self.last_query = query

        self.cancel_event.clear()
        self.update_status("Menganalisis permintaan...", is_working=True)

        worker_thread = threading.Thread(
            target=self._process_request_worker,
            args=(query,),
            daemon=True,
            name="JarvisRequestWorker",
        )
        worker_thread.start()

    def on_voice_clicked(self) -> None:
        """Handle push-to-talk voice recording toggle in the chat UI."""
        from assistant.voice.voice_controller import voice_controller

        if not self._is_recording_voice:
            try:
                voice_controller.start_push_to_talk()
                self._is_recording_voice = True
                self.btn_voice.configure(
                    text="⏹ Selesai",
                    bg=self.THEME["accent_red"],
                    fg=self.THEME["bg_dark"],
                )
                self.update_status("Merekam suara... klik 'Selesai' jika sudah.", is_working=True)
            except Exception as e:
                self.update_status(f"Gagal microphone: {e}", is_working=False)
                self.append_message("System", f"Microphone error: {e}", tag="system")
        else:
            self.btn_voice.configure(
                text="⏳ Memproses...",
                state="disabled",
            )
            self.update_status("Memproses transkripsi suara lokal...", is_working=True)

            def _transcribe_worker():
                try:
                    ok, transcript, stt_res = voice_controller.stop_and_transcribe()
                    self._is_recording_voice = False

                    def _update_ui():
                        self.btn_voice.configure(
                            text="🎤 Suara",
                            bg=self.THEME["bg_card"],
                            fg=self.THEME["accent_peach"],
                            state="normal",
                        )
                        if ok and transcript:
                            self.input_entry.delete(0, tk.END)
                            self.input_entry.insert(0, transcript)
                            self.update_status(f"Suara ditranskripsi: '{transcript}'", is_working=False)
                            self.on_send_clicked()
                        else:
                            self.update_status(transcript, is_working=False)
                            self.append_message("System", transcript, tag="system")

                    self.root.after(0, _update_ui)
                except Exception as ex:
                    self._is_recording_voice = False
                    def _err_ui():
                        self.btn_voice.configure(
                            text="🎤 Suara",
                            bg=self.THEME["bg_card"],
                            fg=self.THEME["accent_peach"],
                            state="normal",
                        )
                        self.update_status(f"Error suara: {ex}", is_working=False)
                    self.root.after(0, _err_ui)

            threading.Thread(target=_transcribe_worker, daemon=True).start()

    def on_cancel_clicked(self) -> None:
        if self._is_recording_voice:
            from assistant.voice.voice_controller import voice_controller
            voice_controller.cancel()
            self._is_recording_voice = False
            self.btn_voice.configure(
                text="🎤 Suara",
                bg=self.THEME["bg_card"],
                fg=self.THEME["accent_peach"],
                state="normal",
            )
            self.update_status("Perekaman suara dibatalkan.", is_working=False)
            self.append_message("System", "Perekaman suara dibatalkan oleh pengguna.", tag="system")
            return

        if self._is_working:
            self.cancel_event.set()
            self.update_status("Membatalkan operasi...", is_working=False)
            self.append_message("Sistem", "Operasi dibatalkan oleh pengguna.", tag="system")

    def _process_request_worker(self, query: str) -> None:
        """Worker thread to run orchestrator without freezing Tkinter UI."""
        start_time = time.perf_counter()
        try:
            # Check if query looks like a diagnostic request to update status nicely
            lower_q = query.lower()
            if "bsod" in lower_q or "crash" in lower_q:
                self.update_status("Mengecek Event Log dan Minidump...", is_working=True)
            elif "disk" in lower_q:
                self.update_status("Menganalisis aktivitas disk dan I/O proses...", is_working=True)
            elif "lemot" in lower_q:
                self.update_status("Mengecek CPU, memori, dan startup items...", is_working=True)

            res = self.orch.handle_request(query)
            self.last_result = res
            elapsed = time.perf_counter() - start_time

            if self.cancel_event.is_set():
                return

            route = res.get("route", "unknown")
            res_type = res.get("type", "response")
            response_text = res.get("response", "Tidak ada respon.")

            sender_name = "Jarvis"
            tag_name = "jarvis"

            if route == "fast":
                sender_name = f"Jarvis (Fast Path: {res.get('intent', 'launch')})"
                tag_name = "jarvis"
            elif res.get("playbook"):
                sender_name = f"Jarvis Diagnosa ({res.get('playbook')})"
                tag_name = "diagnostics"

            self.append_message(sender_name, response_text, tag=tag_name)
            self.update_status(f"Selesai dalam {elapsed:.2f} detik", is_working=False)

        except Exception as e:
            self.update_status("Terjadi kesalahan", is_working=False)
            self.append_message("Jarvis", f"Maaf, terjadi kesalahan saat memproses permintaan: {e}", tag="system")

    def save_current_report(self) -> None:
        """Save the last interaction to a markdown report."""
        if not self.last_result:
            messagebox.showinfo("Simpan Laporan", "Belum ada hasil diagnosa untuk disimpan.")
            return

        title = self.last_result.get("playbook") or self.last_result.get("tool") or "Sesi Diagnosa"
        response_text = self.last_result.get("response", "")
        findings = self.last_result.get("findings")
        rule_findings = self.last_result.get("rule_findings")

        saved_path = save_markdown_report(
            title=title,
            query=self.last_query,
            response=response_text,
            findings=findings,
            rule_findings=rule_findings,
            playbook_name=self.last_result.get("playbook"),
            tool_name=self.last_result.get("tool"),
        )

        messagebox.showinfo("Laporan Disimpan", f"Laporan diagnosa berhasil disimpan di:\n{saved_path.resolve()}")

    def show(self) -> None:
        """Show and bring window to front."""
        def _do_show():
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after_idle(self.root.attributes, "-topmost", False)
            self.input_entry.focus_set()

        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            self.root.after(0, _do_show)

    def hide(self) -> None:
        """Hide window into system tray."""
        self.root.withdraw()
        if self.on_hide_callback:
            self.on_hide_callback()

    def toggle(self) -> None:
        """Toggle window visibility."""
        if self.root.winfo_viewable():
            self.hide()
        else:
            self.show()

    def run_main_loop(self) -> None:
        """Start the Tkinter event loop."""
        self.root.mainloop()

    def destroy(self) -> None:
        """Cleanly destroy window."""
        self.root.quit()
        self.root.destroy()
