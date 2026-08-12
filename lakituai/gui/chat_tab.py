"""Chat tab for the LakituAI GUI.

The user talks to the LakituAI assistant through a ChatSession. The
session is created once in App (so the conversation survives tab
switches) and passed in here.

While the conversation is empty, a centered welcome screen (image +
greeting text) is shown instead of the message history, so the tab
does not look blank on first open.
"""

import threading

import customtkinter

from lakituai.chat.agents import get_model_status
from lakituai.gui.hardware import get_total_vram_gb, vram_warning_message
from lakituai.runtime_paths import assets_dir

ASSETS_DIR = assets_dir()
WELCOME_IMAGE = ASSETS_DIR / "chat_welcome.png"
WELCOME_IMAGE_WIDTH = 240


class ChatTab(customtkinter.CTkFrame):
    """Chat with the LakituAI assistant."""

    def __init__(self, master, chat_session):
        super().__init__(master, fg_color="transparent")
        self.chat_session = chat_session
        self._message_count = 0
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Chat history
        self.chat_history = customtkinter.CTkTextbox(self, wrap="word", state="disabled")
        self.chat_history.grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="nsew"
        )

        # Welcome screen, shown only while there are no messages yet
        self.welcome = customtkinter.CTkFrame(self, fg_color="transparent")
        self.welcome.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.welcome.grid_rowconfigure(0, weight=1)
        self.welcome.grid_rowconfigure(3, weight=1)
        self.welcome.grid_columnconfigure(0, weight=1)

        image = self._load_welcome_image()
        if image is not None:
            self.welcome_image = customtkinter.CTkLabel(
                self.welcome, image=image, text=""
            )
            self.welcome_image.grid(row=1, column=0, pady=(0, 12))

        customtkinter.CTkLabel(
            self.welcome,
            text="LakituAI",
            font=customtkinter.CTkFont(size=30, weight="bold"),
        ).grid(row=2, column=0, pady=(0, 6))

        customtkinter.CTkLabel(
            self.welcome,
            text="Ask me about races, players, or your war standings.",
            font=customtkinter.CTkFont(size=14),
            text_color="gray",
        ).grid(row=3, column=0)

        # Chat entry
        self.chat_entry = customtkinter.CTkEntry(self, placeholder_text="Ask LakituAI")
        self.chat_entry.grid(row=1, column=0, padx=(10, 5), pady=(0, 10), sticky="ew")
        self.chat_entry.bind("<Return>", lambda event: self._send_message())

        # Send button
        self.chat_send_button = customtkinter.CTkButton(
            self, text=">", width=90, command=self._send_message
        )
        self.chat_send_button.grid(row=1, column=1, padx=(0, 10), pady=(0, 10))

        # Low-VRAM warning, shown only below the input bar when needed
        self.vram_warning = customtkinter.CTkLabel(
            self,
            text="",
            text_color="#e05d5d",
            font=customtkinter.CTkFont(size=12),
            anchor="w",
            justify="left",
        )
        self.vram_warning.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        self._show_vram_warning()

        # Model availability status, shown only when the chat must be blocked
        self.model_status = customtkinter.CTkLabel(
            self,
            text="",
            text_color="#e05d5d",
            font=customtkinter.CTkFont(size=12),
            anchor="w",
            justify="left",
            wraplength=900,
        )

        self.retry_button = customtkinter.CTkButton(
            self, text="↻ Retry", width=90, command=self._check_model_status
        )

        self._check_model_status()

        self.chat_entry.focus_set()

    def _load_welcome_image(self):
        """Load the welcome logo, or None if no image asset exists."""
        if not WELCOME_IMAGE.exists():
            return None
        try:
            from PIL import Image

            img = Image.open(WELCOME_IMAGE)
            w, h = img.size
            ratio = h / w
            size = (WELCOME_IMAGE_WIDTH, round(WELCOME_IMAGE_WIDTH * ratio))
            return customtkinter.CTkImage(
                light_image=img,
                dark_image=img,
                size=size,
            )
        except Exception:
            return None

    def _show_vram_warning(self):
        """Show a red warning below the input bar if VRAM is too low."""
        message = vram_warning_message(get_total_vram_gb())
        if message:
            self.vram_warning.configure(text=f"⚠ {message}")
        else:
            self.vram_warning.grid_forget()

    def _check_model_status(self):
        """Check model availability in a thread, then block/unblock the chat."""
        self.retry_button.configure(state="disabled", text="Checking…")
        threading.Thread(target=self._check_model_status_worker, daemon=True).start()

    def _check_model_status_worker(self):
        if self.chat_session is None:
            message = (
                "Chat is unavailable: could not load the chatbot (Ollama)."
            )
        else:
            try:
                message = get_model_status()
            except Exception as e:
                message = f"Chat is unavailable: {e}"
        self.after(0, lambda: self._apply_model_status(message))

    def _apply_model_status(self, message):
        """Enable the chat when the model is ready, or show a blocker message."""
        self.retry_button.configure(state="normal", text="↻ Retry")

        if message is None:
            self.chat_entry.configure(state="normal")
            self.chat_send_button.configure(state="normal")
            self.model_status.grid_remove()
            self.retry_button.grid_remove()
        else:
            self.chat_entry.configure(state="disabled")
            self.chat_send_button.configure(state="disabled")
            self.model_status.configure(text=message)
            self.model_status.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
            self.retry_button.grid(row=3, column=1, padx=(0, 10), pady=(0, 10))

    def _append_chat(self, role: str, message: str):
        self._message_count += 1
        if self._message_count == 1:
            # First message: swap the welcome screen for the history.
            self.welcome.grid_forget()
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", f"{role}: {message}\n\n")
        self.chat_history.configure(state="disabled")
        self.chat_history.see("end")  # Auto scroll to end

    def _send_message(self):
        text = self.chat_entry.get().strip()
        if not text:
            return
        self.chat_entry.delete(0, "end")
        self._append_chat("You", text)

        # Disable while thinking
        self.chat_send_button.configure(state="disabled")

        threading.Thread(target=self._ask_chatbot, args=(text,), daemon=True).start()

    def _ask_chatbot(self, text):
        if self.chat_session is None:
            self.after(
                0,
                lambda: self._show_answer(
                    "Chat is unavailable: could not load the chatbot (Ollama)."
                ),
            )
            return

        try:
            answer = self.chat_session.respond(text)
        except Exception as e:
            answer = (
                f"Error: {e}\nMake sure Ollama is running (ollama serve) and the model is pulled."
            )

        # IMPORTANT: do not modify widgets from a thread other than the main thread.
        # Use `self.after` to return to the GUI's thread.
        self.after(0, lambda: self._show_answer(answer))

    def _show_answer(self, text):
        self._append_chat("LakituAI", text)
        self.chat_send_button.configure(state="normal")
