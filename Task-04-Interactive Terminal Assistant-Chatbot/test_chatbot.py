"""Automated tests for chatbot.py; run with: python -m unittest -v"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import chatbot

# Keep expected warnings (unmatched input) out of the test console.
chatbot.logger.addHandler(__import__("logging").NullHandler())

SAMPLE = {
    "greetings": ["hello", "hi", "hey", "good morning"],
    "faqs": [
        {
            "question": "What are your hours of operation?",
            "answer": "We operate Monday through Friday from 9:00 AM to 6:00 PM IST.",
            "keywords": ["hour", "open", "close", "what time"],
            "details": "We are closed on weekends.",
        },
        {
            "question": "How do I submit my internship project?",
            "answer": "Submit your public GitHub repository link through your Student Workspace.",
            "keywords": ["submit", "submission", "github", "repo"],
        },
        {
            "question": "When will I receive my certificate?",
            "answer": "Certificates are issued within 3-5 business days after code review.",
            "keywords": ["certificate"],
        },
    ],
}

# The official faq.json: no "keywords" or "details" fields. The bot must
# work with exactly this structure.
PROVIDED = {
    "greetings": ["hello", "hi", "hey", "good morning", "good afternoon"],
    "faqs": [
        {
            "question": "What are your hours of operation?",
            "answer": "We operate Monday through Friday from 9:00 AM to "
                      "6:00 PM IST.",
        },
        {
            "question": "How do I submit my internship project?",
            "answer": "You can submit your public GitHub repository link "
                      "through your Student Workspace.",
        },
        {
            "question": "When will I receive my certificate?",
            "answer": "Certificates are reviewed and issued within 3-5 "
                      "business days after your code review.",
        },
    ],
}


def load_sample(data):
    """Write data to a temp faq.json and load it through load_faq_data."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "faq.json"
        path.write_text(
            data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
        )
        with mock.patch.object(chatbot, "FAQ_FILE", path):
            return chatbot.load_faq_data()


class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.greetings, self.faqs = load_sample(SAMPLE)

    def ask(self, message, last=None):
        """Return (reply, last_faq) for one turn, starting from `last`."""
        session = chatbot.Session(last_faq=last)
        text = chatbot.get_response(
            message, self.greetings, self.faqs, session
        )
        return text, session.last_faq

    def test_empty_input(self):
        text, _ = self.ask("   ")
        self.assertIn("Please enter a message", text)

    def test_pure_greeting(self):
        text, _ = self.ask("Hi")
        self.assertIn("Hello!", text)

    def test_greeting_with_question_answers_question(self):
        text, faq = self.ask("Hi, when will I receive my certificate?")
        self.assertIn("3-5 business days", text)
        self.assertEqual(faq["question"], SAMPLE["faqs"][2]["question"])

    def test_word_starting_with_greeting_is_not_greeting(self):
        had, _ = chatbot.split_greeting("history of rome", self.greetings)
        self.assertFalse(had)

    def test_hours_by_keyword(self):
        text, _ = self.ask("What time do you close?")
        self.assertIn("9:00 AM to 6:00 PM", text)

    def test_exact_question_match(self):
        text, _ = self.ask("How do I submit my internship project?")
        self.assertIn("GitHub", text)

    def test_plural_keyword(self):
        text, _ = self.ask("Do you give certificates?")
        self.assertIn("issued", text)

    def test_thanks_plus_question_answers_question(self):
        text, _ = self.ask("Thanks, but how do I submit my project?")
        self.assertIn("GitHub", text)

    def test_plain_thanks(self):
        text, _ = self.ask("thanks")
        self.assertIn("welcome", text.lower())

    def test_unknown_query_fallback(self):
        text, faq = self.ask("What is the weather on Mars?")
        self.assertIn("couldn't find a matching answer", text)
        self.assertIsNone(faq)

    def test_follow_up_uses_details(self):
        _, faq = self.ask("What are your hours?")
        text, _ = self.ask("Tell me more", faq)
        self.assertIn("closed on weekends", text)

    def test_follow_up_without_details(self):
        _, faq = self.ask("How do I submit my project?")
        text, _ = self.ask("tell me more", faq)
        self.assertIn("all the detail I have", text)

    def test_follow_up_without_context(self):
        text, _ = self.ask("tell me more", None)
        self.assertIn("What would you like more information about", text)

    def test_exit_commands(self):
        for word in chatbot.EXIT_COMMANDS:
            text, _ = self.ask(word)
            self.assertIn("Goodbye", text)

    def test_help_lists_questions(self):
        text, _ = self.ask("help")
        self.assertIn("hours of operation", text.lower())


class LoadTests(unittest.TestCase):
    def test_load_valid(self):
        greetings, faqs = load_sample(SAMPLE)
        self.assertIn("hello", greetings)
        self.assertEqual(len(faqs), 3)

    def test_keywords_and_details_optional(self):
        _, faqs = load_sample({"greetings": [], "faqs": [
            {"question": "Q?", "answer": "A."}]})
        self.assertEqual(faqs[0]["keywords"], [])
        self.assertIsNone(faqs[0]["details"])

    def test_invalid_json(self):
        with self.assertRaises(ValueError):
            load_sample("{not valid json")

    def test_root_must_be_object(self):
        with self.assertRaises(ValueError):
            load_sample([])

    def test_blank_greeting_rejected(self):
        with self.assertRaises(ValueError):
            load_sample({"greetings": [""], "faqs": []})

    def test_missing_answer_rejected(self):
        with self.assertRaises(ValueError):
            load_sample({"greetings": [], "faqs": [{"question": "Q?"}]})

    def test_bad_keywords_rejected(self):
        with self.assertRaises(ValueError):
            load_sample({"greetings": [], "faqs": [
                {"question": "Q?", "answer": "A.", "keywords": "nope"}]})

    def test_missing_file(self):
        with mock.patch.object(chatbot, "FAQ_FILE", Path("/nonexistent/faq.json")):
            with self.assertRaises(FileNotFoundError):
                chatbot.load_faq_data()

    def test_real_faq_json_loads(self):
        """The shipped faq.json should always be valid."""
        chatbot.load_faq_data()


class ProvidedFaqTests(unittest.TestCase):
    """Behavior with the official faq.json (no keywords/details)."""

    HOURS = "9:00 AM to 6:00 PM"
    SUBMIT = "GitHub repository"
    CERT = "3-5 business days"

    def setUp(self):
        self.greetings, self.faqs = load_sample(PROVIDED)

    def reply(self, message, last=None):
        """Return (reply, last_faq) for one turn, starting from `last`."""
        session = chatbot.Session(last_faq=last)
        text = chatbot.get_response(
            message, self.greetings, self.faqs, session
        )
        return text, session.last_faq

    def test_rephrasings_without_keywords_field(self):
        cases = {
            "What are your hours of operation?": self.HOURS,
            "What time do you close?": self.HOURS,
            "Are you open on Saturday?": self.HOURS,
            "working hours": self.HOURS,
            "How can I upload my project to GitHub?": self.SUBMIT,
            "where do I send my repo": self.SUBMIT,
            "When do certificates arrive?": self.CERT,
            "Hi, when will I receive my certificate?": self.CERT,
            "Thanks, but how do I submit my project?": self.SUBMIT,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                text, _ = self.reply(message)
                self.assertIn(expected, text)

    def test_single_shared_word_does_not_match(self):
        # One shared word is too weak to answer, but is close enough to
        # offer a "Did you mean...?" instead of a flat refusal.
        for message in ("What is the internship duration?",
                        "How long is the internship?",
                        "Is the project graded?"):
            with self.subTest(message=message):
                text, faq = self.reply(message)
                self.assertNotIn("GitHub", text)
                self.assertIn("Did you mean", text)
                self.assertIsNone(faq)

    def test_no_shared_word_gets_plain_fallback(self):
        text, faq = self.reply("What is the weather on Mars?")
        self.assertIn("couldn't find a matching answer", text)
        self.assertNotIn("Did you mean", text)
        self.assertIsNone(faq)

    def test_follow_up_recaps_when_no_details(self):
        _, faq = self.reply("What are your hours?")
        text, _ = self.reply("tell me more", faq)
        self.assertIn("all the detail I have", text)
        self.assertIn(self.HOURS, text)

    def test_greeting_variants(self):
        for greeting in PROVIDED["greetings"]:
            with self.subTest(greeting=greeting):
                text, _ = self.reply(greeting.title())
                self.assertIn("Hello!", text)


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.greetings, self.faqs = load_sample(SAMPLE)

    def test_unmatched_input_is_logged(self):
        with self.assertLogs("chatbot", level="WARNING") as logs:
            chatbot.get_response(
                "What is the weather on Mars?", self.greetings, self.faqs,
                chatbot.Session(),
            )
        self.assertIn("No match for input", logs.output[0])

    def test_matched_faq_is_logged(self):
        with self.assertLogs("chatbot", level="INFO") as logs:
            chatbot.get_response(
                "when do I get my certificate", self.greetings, self.faqs,
                chatbot.Session(),
            )
        self.assertIn("Matched FAQ", logs.output[0])

    def test_main_logs_load_error_and_tells_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "faq.json"
            bad.write_text("{not valid json", encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(chatbot, "FAQ_FILE", bad), \
                    mock.patch.object(chatbot, "setup_logging"), \
                    self.assertLogs("chatbot", level="ERROR") as logs, \
                    contextlib.redirect_stdout(out):
                chatbot.main()
        self.assertIn("Could not load", logs.output[0])
        self.assertIn("Invalid JSON", out.getvalue())

    def test_setup_logging_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "chatbot.log"
            saved = chatbot.logger.handlers[:]
            chatbot.logger.handlers.clear()
            try:
                with mock.patch.object(chatbot, "LOG_FILE", log):
                    chatbot.setup_logging()
                    chatbot.setup_logging()
                    self.assertEqual(len(chatbot.logger.handlers), 1)
                    chatbot.logger.info("hello log")
                    for h in chatbot.logger.handlers:
                        h.flush()
                    self.assertIn("hello log", log.read_text(encoding="utf-8"))
            finally:
                for h in chatbot.logger.handlers:
                    h.close()
                chatbot.logger.handlers[:] = saved


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text):
    return ANSI.sub("", text)


def capture(func, *args):
    """Run func(*args) and return everything it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        func(*args)
    return out.getvalue()


class TerminalUITests(unittest.TestCase):
    def setUp(self):
        _, self.faqs = load_sample(PROVIDED)

    def make(self, **kwargs):
        options = dict(color=False, width=100, unicode=True,
                       interactive=False)
        options.update(kwargs)
        return chatbot.TerminalUI(**options)

    def test_plain_when_not_a_terminal(self):
        # Piped output: no ANSI codes, no cursor tricks. stdin/stdout are
        # replaced explicitly so the test passes inside a real terminal too.
        with mock.patch.object(chatbot.sys, "stdout", io.StringIO()), \
                mock.patch.object(chatbot.sys, "stdin", io.StringIO()):
            ui = chatbot.TerminalUI()
        self.assertFalse(ui.color)
        self.assertFalse(ui.interactive)
        out = capture(ui.assistant_message, "Hello")
        self.assertNotIn("\x1b", out)

    def test_color_codes_only_when_enabled(self):
        colored = capture(self.make(color=True).assistant_message, "Hi")
        self.assertIn("\x1b[", colored)
        self.assertNotIn("\x1b", capture(self.make().assistant_message, "Hi"))
        self.assertEqual(strip_ansi(colored),
                         capture(self.make().assistant_message, "Hi"))

    def test_banner_and_panels_fit_every_width(self):
        for width in (50, 64, 80, 89, 90, 100):
            for use_unicode in (True, False):
                ui = self.make(width=width, unicode=use_unicode, color=True)
                out = strip_ansi(capture(ui.welcome, self.faqs))
                for line in out.splitlines():
                    with self.subTest(width=width, unicode=use_unicode,
                                      line=line):
                        self.assertLessEqual(
                            chatbot.display_width(line), width
                        )

    def test_boxes_are_rectangular(self):
        # Every row of the banner has the full width, so borders line up.
        # Width is measured in terminal columns: full-width letters in the
        # title take two columns each.
        for width in (60, 80, 100):
            ui = self.make(width=width)
            rows = [r for r in capture(ui.banner).splitlines() if r]
            with self.subTest(width=width):
                self.assertEqual(
                    {chatbot.display_width(r) for r in rows}, {width}
                )

    def test_side_by_side_panels_on_wide_terminals(self):
        wide = capture(self.make(width=100).panels, self.faqs)
        narrow = capture(self.make(width=80).panels, self.faqs)
        self.assertIn("Quick Help", wide.splitlines()[0])
        self.assertIn("Sample Questions", wide.splitlines()[0])
        self.assertNotIn("Sample Questions", narrow.splitlines()[0])

    def test_welcome_content(self):
        out = capture(self.make().welcome, self.faqs)
        for text in (chatbot.SUBTITLE,
                     "Business hours",
                     "Internship project submission",
                     "Certificate status and delivery",
                     "What are your hours of operation?", "Tell me more",
                     "Type 'help' for more options.", "Chatbot Online",
                     "Ready to help!", chatbot.TAGLINE):
            with self.subTest(text=text):
                self.assertIn(text, out)

    def test_user_bubble_is_right_aligned(self):
        out = capture(self.make(width=80).user_message, "hello")
        rows = [r for r in out.splitlines() if r.strip()]
        self.assertTrue(rows[0].rstrip().endswith("You"))
        for row in rows[1:]:
            self.assertEqual(len(row), 79)  # one-column right margin

    def test_assistant_bubble_is_left_aligned_with_label(self):
        out = capture(self.make().assistant_message, "Hello there")
        rows = [r for r in out.splitlines() if r.strip()]
        self.assertIn("Assistant", rows[0])
        self.assertRegex(rows[0], r"\b\d{2}:\d{2}\b")
        self.assertTrue(all(r.startswith("  ") for r in rows))

    def test_long_message_wraps_inside_the_bubble(self):
        long_text = "word " * 80
        for method in ("user_message", "assistant_message"):
            ui = self.make(width=80)
            out = capture(getattr(ui, method), long_text)
            for line in out.splitlines():
                with self.subTest(method=method):
                    self.assertLessEqual(len(line), 80)
            self.assertGreater(len(out.splitlines()), 5)

    def test_bullets_hang_when_wrapped(self):
        lines = chatbot.wrap_text("  \u2022 " + "long " * 20, 30)
        self.assertTrue(lines[0].startswith("  \u2022"))
        self.assertTrue(all(l.startswith("    ") for l in lines[1:]))

    def test_ascii_fallback_is_pure_ascii(self):
        ui = self.make(unicode=False)
        out = capture(ui.welcome, self.faqs)
        out += capture(ui.user_message, "hi")
        out += capture(ui.assistant_message, "hello")
        out.encode("ascii")  # raises if any non-ASCII character slipped in

    def test_unicode_detection_follows_stdout_encoding(self):
        class Fake:
            encoding = "ascii"

        with mock.patch.object(chatbot.sys, "stdout", Fake()):
            self.assertFalse(chatbot.TerminalUI._can_encode())

    def test_read_input_plain_when_piped(self):
        with mock.patch("builtins.input", return_value="hi there"):
            self.assertEqual(self.make().read_input(), "hi there")

    def test_topic_labels(self):
        self.assertEqual(chatbot.topic_for("What are your hours of operation?"),
                         "Business hours")
        self.assertEqual(
            chatbot.topic_for("How do I submit my internship project?"),
            "Internship project submission")
        self.assertEqual(chatbot.topic_for("Do you offer remote work?"),
                         "Do you offer remote work")

    def test_full_session_renders_like_the_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faq.json"
            path.write_text(json.dumps(PROVIDED), encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(chatbot, "FAQ_FILE", path), \
                    mock.patch.object(chatbot, "setup_logging"), \
                    mock.patch("builtins.input",
                               side_effect=["hello", "what time do you close",
                                            "bye"]), \
                    contextlib.redirect_stdout(out):
                chatbot.main()
        text = out.getvalue()
        self.assertIn("Chatbot Online", text)
        self.assertEqual(text.count("You\n"), 3)  # one label per user turn
        self.assertIn("Welcome to the Interactive Terminal Assistant", text)
        self.assertIn("9:00 AM to 6:00 PM IST", text)
        self.assertIn("Goodbye! Thank you for chatting. Have a great day!", text)


class BannerTitleTests(unittest.TestCase):
    """Title: sparkles + ordinary bold letters + gold-to-teal gradient."""

    TITLE = "✦ C H A T B O T ✦"
    SUBTITLE = chatbot.SUBTITLE

    def make(self, **kwargs):
        options = dict(color=False, width=100, unicode=True,
                       interactive=False)
        options.update(kwargs)
        return chatbot.TerminalUI(**options)

    def test_bold_sans_conversion(self):
        self.assertEqual(
            chatbot.to_bold_sans("Ab1 -"),
            chr(0x1D5D4) + chr(0x1D5EF) + chr(0x1D7ED) + " -",
        )
        # Bold sans letters take one terminal column, like plain letters.
        self.assertEqual(chatbot.display_width(chatbot.to_bold_sans("Ab")), 2)

    def test_title_uses_ordinary_ascii_letters(self):
        out = capture(self.make().banner)
        self.assertEqual(chatbot.TITLE_FONT, "plain")
        rows = [r for r in out.splitlines() if "C H A T B O T" in r]
        self.assertEqual(len(rows), 1)
        # Between the sparkles every character is plain ASCII: clear to
        # read and exactly one terminal column wide.
        letters = rows[0].split("✦")[1]
        self.assertTrue(letters.isascii())
        self.assertTrue(chatbot.SUBTITLE.isascii())

    def test_title_is_sparkled_bold_letters(self):
        out = capture(self.make().banner)
        self.assertNotIn("Datheon", out)
        self.assertIn(self.TITLE, out)
        self.assertIn(self.SUBTITLE, out)
        self.assertNotIn("█", out)  # normal letters, not block art
        # Tag row, title row and subtitle row beside the 3-row robot.
        self.assertEqual(len(out.splitlines()), 5)

    def test_title_letters_fade_from_gold_to_teal(self):
        colored = capture(self.make(color=True).banner)
        codes = set(re.findall(r"\x1b\[(38;5;\d+);1m", colored))
        for step in chatbot.TITLE_GRADIENT:
            with self.subTest(step=step):
                self.assertIn(step, codes)
        # Colors change nothing about the visible text.
        self.assertIn(self.TITLE, strip_ansi(colored))

    def test_subtitle_is_bold_gold(self):
        out = capture(self.make(color=True).banner)
        bold_gold = f"\x1b[{chatbot.GOLD};{chatbot.BOLD}m"
        self.assertIn(bold_gold + self.SUBTITLE, out)

    def test_ascii_mode_uses_plain_sparkled_title(self):
        out = capture(self.make(unicode=False).banner)
        self.assertIn("* C H A T B O T *", out)
        self.assertIn(chatbot.SUBTITLE, out)
        out.encode("ascii")

    def test_font_can_be_switched(self):
        with mock.patch.object(chatbot, "TITLE_FONT", "fullwidth"):
            out = capture(self.make().banner)
        self.assertIn(chatbot.to_fullwidth("C"), out)
        with mock.patch.object(chatbot, "TITLE_FONT", "bold"):
            out = capture(self.make().banner)
        self.assertIn(chatbot.to_bold_sans("C"), out)

    def test_title_falls_back_when_space_is_tight(self):
        ui = self.make()
        self.assertEqual(ui._fit_title(100), self.TITLE)
        self.assertEqual(ui._fit_title(13), "C H A T B O T")
        self.assertEqual(ui._fit_title(10), "CHATBOT")

    def test_every_width_fits_and_keeps_title(self):
        for width in (50, 60, 80, 90, 100):
            for use_unicode in (True, False):
                out = capture(
                    self.make(width=width, unicode=use_unicode).banner
                )
                title = self.TITLE if use_unicode else "* C H A T B O T *"
                with self.subTest(width=width, unicode=use_unicode):
                    self.assertIn(title, out)
                    for line in out.splitlines():
                        self.assertLessEqual(
                            chatbot.display_width(line), width
                        )


class StateTests(unittest.TestCase):
    """greeting -> intent identification -> resolution -> exit."""

    def setUp(self):
        self.greetings, self.faqs = load_sample(PROVIDED)
        self.session = chatbot.Session()

    def say(self, message):
        return chatbot.get_response(
            message, self.greetings, self.faqs, self.session
        )

    def test_starts_in_greeting_state(self):
        self.assertIs(self.session.state, chatbot.State.GREETING)
        self.assertIsNone(self.session.last_faq)

    def test_full_conversation_flow(self):
        self.say("hello")
        self.assertIs(self.session.state, chatbot.State.IDENTIFYING)
        self.say("what time do you close")
        self.assertIs(self.session.state, chatbot.State.RESOLVED)
        self.assertEqual(self.session.last_faq["topic"], "Business hours")
        self.say("bye")
        self.assertIs(self.session.state, chatbot.State.EXITED)

    def test_unmatched_question_does_not_resolve(self):
        self.say("what is the weather on mars")
        self.assertIs(self.session.state, chatbot.State.IDENTIFYING)
        self.assertIsNone(self.session.last_faq)

    def test_follow_up_keeps_resolved_state(self):
        self.say("what are your hours")
        self.say("tell me more")
        self.assertIs(self.session.state, chatbot.State.RESOLVED)

    def test_new_question_after_resolution_updates_context(self):
        self.say("what are your hours")
        self.say("when will I receive my certificate")
        self.assertIs(self.session.state, chatbot.State.RESOLVED)
        self.assertEqual(
            self.session.last_faq["topic"], "Certificate status and delivery"
        )

    def test_miss_after_resolution_keeps_previous_context(self):
        self.say("what are your hours")
        self.say("what is the weather on mars")
        self.assertIs(self.session.state, chatbot.State.RESOLVED)
        self.assertEqual(self.session.last_faq["topic"], "Business hours")

    def test_every_exit_command_ends_session(self):
        for word in chatbot.EXIT_COMMANDS:
            with self.subTest(word=word):
                session = chatbot.Session()
                chatbot.get_response(
                    word, self.greetings, self.faqs, session
                )
                self.assertIs(session.state, chatbot.State.EXITED)

    def test_low_confidence_suggests_closest_question(self):
        text = self.say("internship please")
        self.assertIn("Did you mean", text)
        self.assertIn("How do I submit my internship project", text)
        self.assertIsNone(self.session.last_faq)

    def test_main_loop_stops_after_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faq.json"
            path.write_text(json.dumps(PROVIDED), encoding="utf-8")
            out = io.StringIO()
            # The third answer would raise StopIteration if read.
            with mock.patch.object(chatbot, "FAQ_FILE", path), \
                    mock.patch.object(chatbot, "setup_logging"), \
                    mock.patch("builtins.input",
                               side_effect=["hi", "quit"]), \
                    contextlib.redirect_stdout(out):
                chatbot.main()
        self.assertIn("Goodbye!", out.getvalue())


if __name__ == "__main__":
    unittest.main()