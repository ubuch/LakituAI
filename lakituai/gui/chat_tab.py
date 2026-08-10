"""Chat tab for the LakituAI GUI.

The user talks to the LakituAI assistant through a ChatSession. The
session is created once in App (so the conversation survives tab
switches) and passed in here.
"""

import threading

import customtkinter


class ChatTab(customtkinter.CTkFrame):
    """Chat with the LakituAI assistant."""

    def __init__(self, master, chat_session):
        super().__init__(master, fg_color="transparent")
        self.chat_session = chat_session
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Chat history
        self.chat_history = customtkinter.CTkTextbox(self, wrap="word", state="disabled")
        self.chat_history.grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="nsew"
        )

        # Chat entry
        self.chat_entry = customtkinter.CTkEntry(self, placeholder_text="Ask LakituAI")
        self.chat_entry.grid(row=1, column=0, padx=(10, 5), pady=(0, 10), sticky="ew")
        self.chat_entry.bind("<Return>", lambda event: self._send_message())

        # Send button
        self.chat_send_button = customtkinter.CTkButton(
            self, text=">", width=90, command=self._send_message
        )
        self.chat_send_button.grid(row=1, column=1, padx=(0, 10), pady=(0, 10))

        self.chat_entry.focus_set()

    def _append_chat(self, role: str, message: str):
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
