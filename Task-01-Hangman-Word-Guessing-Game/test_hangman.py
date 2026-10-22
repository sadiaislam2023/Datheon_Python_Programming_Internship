"""Automated tests for hangman.py (run with: pytest)."""

import builtins
import contextlib
import io
import logging
from pathlib import Path

import pytest

import hangman
from hangman import (
    DIFFICULTIES,
    GuessResult,
    HangmanGame,
    SessionStats,
    calculate_score,
    choose_option,
    choose_word,
    gallows_colour,
    interpret_guess,
    load_words,
    parse_words,
    vlen,
)

EASY, MEDIUM, HARD = DIFFICULTIES


def new_game(word: str = "python", difficulty=MEDIUM) -> HangmanGame:
    return HangmanGame(word, difficulty)


# ---------- guessing: letters ----------


def test_correct_letter():
    game = new_game()
    assert game.guess_letter("p") is GuessResult.CORRECT
    assert "p" in game.correct_letters
    assert game.mistakes == 0


def test_wrong_letter_costs_one_life():
    game = new_game()
    assert game.guess_letter("z") is GuessResult.INCORRECT
    assert game.mistakes == 1
    assert game.attempts_left == game.max_attempts - 1


def test_letter_guess_is_case_insensitive():
    game = new_game()
    assert game.guess_letter("P") is GuessResult.CORRECT


def test_repeated_correct_letter_is_free():
    game = new_game()
    game.guess_letter("p")
    assert game.guess_letter("p") is GuessResult.REPEAT
    assert game.mistakes == 0


def test_repeated_wrong_letter_is_free():
    game = new_game()
    game.guess_letter("z")
    assert game.guess_letter("z") is GuessResult.REPEAT
    assert game.mistakes == 1  # not charged twice


# ---------- guessing: whole words ----------


def test_correct_word_wins():
    game = new_game()
    assert game.guess_word("PYTHON") is GuessResult.CORRECT
    assert game.is_won and game.is_over and not game.is_lost


def test_wrong_word_costs_one_life():
    game = new_game()
    assert game.guess_word("snake") is GuessResult.INCORRECT
    assert game.mistakes == 1


def test_repeated_wrong_word_is_free():
    game = new_game()
    game.guess_word("snake")
    assert game.guess_word("snake") is GuessResult.REPEAT
    assert game.mistakes == 1


# ---------- win / loss flags ----------


def test_win_by_letters():
    game = new_game("cat")
    for letter in "cat":
        game.guess_letter(letter)
    assert game.is_won and game.is_over and not game.is_lost


def test_loss_after_six_wrong_guesses():
    game = new_game()
    for letter in "abcdef":  # none of these are in "python"
        assert not game.is_over
        game.guess_letter(letter)
    assert game.is_lost and game.is_over and not game.is_won
    assert game.attempts_left == 0


def test_mixed_wrong_letters_and_words_count_together():
    game = new_game()
    game.guess_letter("a")
    game.guess_letter("b")
    game.guess_word("one")
    game.guess_word("two")
    game.guess_word("three")
    game.guess_word("four")
    assert game.mistakes == 6 and game.is_lost


def test_attempts_left_never_negative_and_stage_capped():
    game = new_game()
    for letter in "abcdefgijk":
        game.guess_letter(letter)
    assert game.attempts_left == 0
    assert game.stage == hangman.CLASSIC_ATTEMPTS


def test_new_game_is_not_over():
    game = new_game()
    assert not game.is_over


# ---------- masked word ----------


def test_masked_word_hides_and_reveals():
    game = new_game("cat")
    game.guess_letter("a")
    assert game.masked_word() == [("_", False), ("A", True), ("_", False)]
    assert all(shown for _, shown in game.masked_word(reveal=True))


# ---------- hints ----------


def test_hint_reveals_a_hidden_letter():
    game = new_game("python", MEDIUM)
    letter = game.use_hint()
    assert letter in "python"
    assert letter in game.correct_letters
    assert game.hints_used == 1


def test_hints_are_limited_by_difficulty():
    game = new_game("elephant", HARD)  # Hard has 1 hint
    assert game.use_hint() is not None
    assert game.hints_left == 0
    assert game.use_hint() is None


def test_hint_refused_when_one_letter_left():
    game = new_game("cat")
    game.guess_letter("c")
    game.guess_letter("a")  # only "t" is hidden
    assert game.use_hint() is None
    assert game.hints_used == 0


# ---------- scoring and statistics ----------


def test_score_formula_and_hint_penalty():
    game = new_game("python", MEDIUM)  # 6 letters, 6 lives left, x1.5
    expected_base = int((50 + 10 * 6 + 15 * 6) * 1.5)
    assert calculate_score(game, streak=1).base == expected_base
    game.use_hint()
    breakdown = calculate_score(game, streak=1)
    assert breakdown.hint_penalty == hangman.HINT_PENALTY
    assert breakdown.total == expected_base - hangman.HINT_PENALTY


def test_streak_bonus_starts_on_second_win():
    game = new_game()
    assert calculate_score(game, streak=1).streak_bonus == 0
    assert calculate_score(game, streak=3).streak_bonus == 40


def test_fewer_mistakes_score_more():
    clean, sloppy = new_game(), new_game()
    sloppy.guess_letter("z")
    assert calculate_score(clean, 1).total > calculate_score(sloppy, 1).total


def test_session_stats_win_and_loss():
    stats = SessionStats()
    stats.record_win(100)
    stats.record_win(50)
    assert (stats.wins, stats.streak, stats.best_streak, stats.score) == (2, 2, 2, 150)
    stats.record_loss()
    assert (stats.losses, stats.streak, stats.best_streak) == (1, 0, 2)


# ---------- gallows colour ----------


def test_gallows_colour_follows_last_guess():
    game = new_game()
    assert gallows_colour(game) == hangman.YELLOW
    game.guess_letter("p")
    game.last_result = GuessResult.CORRECT
    assert gallows_colour(game) == hangman.GREEN
    game.guess_letter("z")
    game.last_result = GuessResult.INCORRECT
    assert gallows_colour(game) == hangman.RED


def test_gallows_colour_on_win_and_loss():
    won = new_game("cat")
    won.guess_word("cat")
    assert gallows_colour(won) == hangman.GREEN
    lost = new_game()
    for letter in "abcdef":
        lost.guess_letter(letter)
    assert gallows_colour(lost) == hangman.RED


# ---------- input handling ----------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a", ("letter", "a")),
        ("A", ("letter", "a")),
        ("  python  ", ("word", "python")),
        ("?", ("hint", "")),
        ("/s", ("settings", "")),
        ("/q", ("quit", "")),
        ("quit", ("quit", "")),
    ],
)
def test_interpret_valid_input(raw, expected):
    assert interpret_guess(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "5", "a1", "hello!", "ice cream", "é", "日本"])
def test_interpret_rejects_non_letters(raw):
    kind, message = interpret_guess(raw)
    assert kind == "invalid"
    assert message


def feed_inputs(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda *a: next(answers))


def test_choose_option_accepts_valid_number(monkeypatch, capsys):
    feed_inputs(monkeypatch, ["3"])
    assert choose_option("T", ["a", "b", "c"]) == 2


def test_choose_option_default_on_enter(monkeypatch, capsys):
    feed_inputs(monkeypatch, [""])
    assert choose_option("T", ["a", "b", "c"], default=1) == 1


@pytest.mark.parametrize("bad", ["0", "4", "-1", "abc", "1.5", "²", "٣"])
def test_choose_option_rejects_bad_numbers_without_crashing(monkeypatch, capsys, bad):
    # "²" used to crash: "²".isdigit() is True but int("²") raises ValueError.
    feed_inputs(monkeypatch, [bad, "2"])
    assert choose_option("T", ["a", "b", "c"]) == 1
    assert "Choose a number from 1 to 3" in capsys.readouterr().out


# ---------- word list ----------


def test_parse_words_categories_and_per_word_category():
    lines = ["# Sports", "tennis", "cricket,Games", "", "# animals", "Giraffe"]
    words = parse_words(lines)
    assert words == {"tennis": "Sports", "cricket": "Games", "giraffe": "Animals"}


def test_parse_words_skips_bad_lines_and_duplicates():
    lines = ["okay", "OKAY", "two words", "abc123", "café", "   ", "fine,X"]
    words = parse_words(lines)
    assert set(words) == {"okay", "fine"}
    assert words["okay"] == hangman.DEFAULT_CATEGORY


def test_parse_words_keeps_short_words_by_default():
    # Every word in the list is playable, including 1-, 2- and 3-letter words
    assert set(parse_words(["a", "ab", "abc", "abcd"])) == {"a", "ab", "abc", "abcd"}


def test_parse_words_respects_min_length():
    assert set(parse_words(["a", "ab", "abc"], min_length=3)) == {"abc"}


def test_load_words_from_file(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# Food\npizza\nsoup\n", encoding="utf-8")
    assert load_words(path) == {"pizza": "Food", "soup": "Food"}


def test_load_words_handles_bom(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("\ufeffpizza\n", encoding="utf-8")
    assert "pizza" in load_words(path)


def test_missing_custom_word_list_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as info:
        load_words(tmp_path / "nope.txt")
    assert info.value.code == 1
    assert "Could not read word list" in capsys.readouterr().out


def test_empty_custom_word_list_exits(tmp_path, capsys):
    path = tmp_path / "empty.txt"
    path.write_text("# only a comment\n123\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_words(path)


# ---------- choosing words ----------

WORDS = {
    "cat": "A",
    "tiger": "A",
    "giraffe": "A",
    "hippopotamus": "A",
    "watermelon": "A",
}


@pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
def test_choose_word_respects_difficulty(difficulty):
    for _ in range(20):
        word = choose_word(difficulty, WORDS, set())
        assert difficulty.min_length <= len(word) <= difficulty.max_length


def test_choose_word_avoids_repeats_until_exhausted():
    used: set = set()
    picked = {choose_word(HARD, WORDS, used) for _ in range(2)}
    assert picked == {"hippopotamus", "watermelon"}
    assert choose_word(HARD, WORDS, used) in picked  # exhausted: repeats allowed


# ---------- difficulty levels ----------


def test_difficulty_ranges_do_not_overlap_and_get_harder():
    for easier, harder in zip(DIFFICULTIES, DIFFICULTIES[1:]):
        assert easier.max_length < harder.min_length  # no word fits two levels
        assert harder.multiplier > easier.multiplier
        assert harder.hints <= easier.hints


@pytest.mark.parametrize("length", range(1, 40))
def test_every_word_length_belongs_to_exactly_one_level(length):
    levels = [d for d in DIFFICULTIES if d.min_length <= length <= d.max_length]
    assert len(levels) == 1


def test_one_letter_word_is_playable():
    game = new_game("a", EASY)
    assert game.use_hint() is None  # nothing to hint at
    assert game.guess_letter("z") is GuessResult.INCORRECT
    assert game.guess_letter("a") is GuessResult.CORRECT
    assert game.is_won


def test_difficulty_summary_text():
    assert EASY.summary == "1-4 letters, 3 hints"
    assert HARD.summary.startswith("8+ letters")


def test_choose_word_falls_back_and_logs(caplog):
    hangman.log.propagate = True  # let caplog see the "hangman" logger
    try:
        with caplog.at_level(logging.WARNING, logger="hangman"):
            word = choose_word(HARD, {"cat": "A"}, set())
    finally:
        hangman.log.propagate = False
    assert word == "cat"
    assert "picking from all words" in caplog.text


# ---------- layout helpers ----------


def test_vlen_ignores_colour_codes():
    assert vlen("\x1b[1;38;2;1;2;3mhello\x1b[0m") == 5


def test_clip_and_fit_keep_exact_width():
    coloured = hangman.style("hello world", hangman.CYAN, bold=True)
    assert vlen(hangman.clip(coloured, 5)) == 5
    assert vlen(hangman.fit(coloured, 20)) == 20
    assert vlen(hangman.fit(coloured, 20, "center")) == 20


def test_panel_rows_have_equal_width():
    rows = hangman.panel(["a", "bbb"], 20, hangman.CYAN)
    assert {vlen(row) for row in rows} == {20}


def test_split_widths_add_up():
    assert sum(hangman.split_widths(100, 3)) + 2 == 100


def test_full_frame_renders_at_every_tier():
    game = new_game()
    for tier in hangman.FRAME_TIERS:
        lines = hangman.build_frame(game, SessionStats(), "msg", hangman.CYAN, width=100, **tier)
        assert all(vlen(line) <= 100 for line in lines)


# ---------- logging setup ----------


def test_setup_logging_writes_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hangman.log, "handlers", [])
    path = tmp_path / "test.log"
    hangman.setup_logging(path)
    hangman.log.info("hello log")
    for handler in hangman.log.handlers:
        handler.flush()
    assert "hello log" in path.read_text(encoding="utf-8")
    for handler in list(hangman.log.handlers):
        handler.close()


def test_setup_logging_survives_unwritable_path(tmp_path, monkeypatch):
    monkeypatch.setattr(hangman.log, "handlers", [])
    hangman.setup_logging(Path(tmp_path) / "no_such_dir" / "x.log")  # must not raise
    hangman.log.info("still fine")


# ---------- intro screen ----------


def test_intro_shows_instructions_directly_under_the_title(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda *a: "")
    monkeypatch.setattr(hangman, "USE_COLOR", False)
    hangman.show_intro()
    screen = capsys.readouterr().out
    assert "HOW TO PLAY" in screen and "THE GALLOWS" in screen
    assert screen.index("HOW TO PLAY") < screen.index("THE GALLOWS")  # rules come first


# ---------- words come only from words.txt ----------


def test_missing_default_word_list_stops_the_game(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "words.txt"
    monkeypatch.setattr(hangman, "DEFAULT_WORDS_FILE", missing)
    with pytest.raises(SystemExit) as info:
        load_words(missing)
    assert info.value.code == 1
    assert "words.txt" in capsys.readouterr().out


def test_empty_default_word_list_stops_the_game(monkeypatch, tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# nothing usable\n", encoding="utf-8")
    monkeypatch.setattr(hangman, "DEFAULT_WORDS_FILE", path)
    with pytest.raises(SystemExit):
        load_words(path)


def test_no_hardcoded_words_in_the_program():
    assert not hasattr(hangman, "BUILTIN_WORDS")


@pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
def test_every_chosen_word_comes_from_the_word_list(tmp_path, difficulty):
    path = tmp_path / "list.txt"
    listed = ["ab", "tree", "apple", "garden", "mountain", "chocolate", "watermelon"]
    path.write_text("\n".join(listed), encoding="utf-8")
    words = load_words(path)
    for _ in range(50):
        assert choose_word(difficulty, words, set()) in listed


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def show_intro_at(monkeypatch, height):
    monkeypatch.setattr(builtins, "input", lambda *a: "")
    monkeypatch.setattr(hangman, "USE_COLOR", False)
    monkeypatch.setattr(hangman, "frame_height", lambda: height)
    screen = FakeTTY()
    with contextlib.redirect_stdout(screen):
        hangman.show_intro()
    return screen.getvalue()


ALL_RULES = ("Goal", "Lives", "Guess", "Repeats", "Hints", "Menu", "Score", "Colors")
CORE_RULES = ("Goal", "Guess", "Menu", "Colors")


@pytest.mark.parametrize("height", [29, 31, 33, 36, 50])
def test_intro_keeps_title_and_gallows_on_short_terminals(monkeypatch, height):
    text = show_intro_at(monkeypatch, height)
    assert "██" in text  # the big title
    assert "THE GALLOWS" in text
    assert all(label in text for label in CORE_RULES)
    assert len(text.rstrip("\n").split("\n")) <= height  # the page never scrolls


@pytest.mark.parametrize("height", [22, 26, 28])
def test_intro_shows_full_instructions_when_there_is_no_room_for_the_gallows(monkeypatch, height):
    text = show_intro_at(monkeypatch, height)
    assert "██" in text
    assert all(label in text for label in ALL_RULES)
    assert len(text.rstrip("\n").split("\n")) <= height


@pytest.mark.parametrize("height", [33, 36, 50])
def test_intro_shows_every_instruction_on_tall_terminals(monkeypatch, height):
    text = show_intro_at(monkeypatch, height)
    assert all(label in text for label in ALL_RULES)