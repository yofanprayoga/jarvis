"""System tray application runner with global hotkey and Tkinter chat window (Section 13)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw
import pystray

from assistant.ui.chat_window import ChatWindow
from assistant.ui.hotkey import GlobalHotkeyListener
from assistant.ui.reports import get_reports_dir


def create_tray_icon_image(size: tuple[int, int] = (64, 64)) -> Image.Image:
    """Generate a sleek, programmatic icon for the Windows system tray."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Outer circle in deep obsidian (#1e1e2e) with cyan ring (#89b4fa)
    draw.ellipse((4, 4, size[0] - 4, size[1] - 4), fill=(30, 30, 46, 255), outline=(137, 180, 250, 255), width=3)

    # Inner core arc / glowing center (#a6e3a1 green)
    draw.ellipse((20, 20, size[0] - 20, size[1] - 20), fill=(166, 227, 161, 255))

    # Center dot (#1e1e2e)
    draw.ellipse((27, 27, size[0] - 27, size[1] - 27), fill=(30, 30, 46, 255))

    return image


class TrayApplication:
    """Manages system tray icon, global hotkey (Ctrl+Shift+J), and chat window lifecycle."""

    def __init__(self) -> None:
        self.window: Optional[ChatWindow] = None
        self.hotkey_listener: Optional[GlobalHotkeyListener] = None
        self.tray_icon: Optional[pystray.Icon] = None
        self._is_exiting = False

    def open_reports_folder(self) -> None:
        """Open reports directory in Windows Explorer."""
        reports_dir = get_reports_dir().resolve()
        os.startfile(str(reports_dir))

    def trigger_quick_diagnosis(self, prompt: str) -> None:
        """Show window and immediately trigger diagnostic command."""
        if not self.window:
            return
        self.window.show()
        self.window._on_quick_action(prompt)

    def on_hotkey_pressed(self) -> None:
        """Handler when Ctrl+Shift+J is pressed globally."""
        if self.window:
            self.window.toggle()

    def exit_application(self) -> None:
        """Clean shutdown of tray, hotkey, and window."""
        if self._is_exiting:
            return
        self._is_exiting = True

        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass

        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass

    def run(self) -> None:
        """Start the tray application (Main Thread runs Tkinter, background threads for tray & hotkey)."""
        # 1. Initialize Chat Window
        self.window = ChatWindow()

        # 2. Register Global Hotkey (Ctrl+Shift+J)
        self.hotkey_listener = GlobalHotkeyListener(callback=self.on_hotkey_pressed)
        hotkey_ok = self.hotkey_listener.start()
        if not hotkey_ok:
            print("[WARN] Global hotkey Ctrl+Shift+J could not be registered (key conflict).", file=sys.stderr)

        # 3. Build Tray Menu & Icon
        menu = pystray.Menu(
            pystray.MenuItem("Buka Chat (Ctrl+Shift+J)", lambda: self.window.show(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Diagnosa Cepat",
                pystray.Menu(
                    pystray.MenuItem("Diagnosa BSOD", lambda: self.trigger_quick_diagnosis("kenapa tadi bsod?")),
                    pystray.MenuItem("Diagnosa Disk 100%", lambda: self.trigger_quick_diagnosis("disk gw 100% terus nih")),
                    pystray.MenuItem("Diagnosa Laptop Lemot", lambda: self.trigger_quick_diagnosis("laptop lemot banget kenapa ya")),
                ),
            ),
            pystray.MenuItem("Folder Laporan", lambda: self.open_reports_folder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Keluar / Exit", lambda: self.exit_application()),
        )

        icon_image = create_tray_icon_image()
        self.tray_icon = pystray.Icon(
            name="JarvisPC",
            icon=icon_image,
            title="Jarvis PC Operator (Aktif)",
            menu=menu,
        )

        # Run tray icon in detached thread so Tkinter owns the main thread
        self.tray_icon.run_detached()

        # 4. Start Tkinter Main Event Loop
        try:
            self.window.run_main_loop()
        except KeyboardInterrupt:
            self.exit_application()


def run_tray_app() -> None:
    """Entry point for tray application."""
    app = TrayApplication()
    app.run()


if __name__ == "__main__":
    run_tray_app()
