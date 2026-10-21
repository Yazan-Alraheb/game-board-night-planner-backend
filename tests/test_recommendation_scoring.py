from dataclasses import replace

import pytest

from app.services.recommendations import (
    GameFeatures, SavedPreferences, categories, category_match, difficulty_match,
    explain, personally_disliked, score_game,
)


GAME = GameFeatures(categories(["Strategy", "Cooperative"]), "Medium", 60)
EMPTY = SavedPreferences()


@pytest.mark.parametrize("values,expected", [
    (None, frozenset()), ([" STRATEGY ", "strategy"], frozenset({"strategy"})),
    ([], frozenset()), (["Party", 5, None, True, {"x": 1}, ["y"], "  "], frozenset({"party"})),
    ("Strategy", frozenset()), ({"Strategy": 1}, frozenset()),
])
def test_category_normalization(values, expected):
    assert categories(values) == expected


@pytest.mark.parametrize("desired,expected", [([], .5), (["Strategy"], 1),
    (["Strategy", "Party"], .5), (["Party"], 0)])
def test_category_fraction(desired, expected):
    assert category_match(GAME.categories, categories(desired)) == expected


@pytest.mark.parametrize("desired,expected", [(None, .5), ("Medium", 1), ("Easy", .5), ("Hard", .5)])
def test_difficulty_partial_credit(desired, expected):
    assert difficulty_match("Medium", desired) == expected
    assert difficulty_match("Easy", "Hard") == 0


@pytest.mark.parametrize("experience,difficulty", [("Beginner", "Easy"),
    ("Intermediate", "Medium"), ("Experienced", "Hard")])
def test_experience_mapping_and_saved_override(experience, difficulty):
    game = replace(GAME, difficulty=difficulty)
    opposite = "Hard" if difficulty == "Easy" else "Easy"
    assert score_game(game, [replace(EMPTY, difficulty=opposite)], frozenset(), experience, group=False) == 67.5


@pytest.mark.parametrize("requested,experience,preference,expected", [
    ([], None, EMPTY, 50),
    (["Strategy"], None, EMPTY, 75),  # +15 request, +10 overridden favorites
    (["Party"], None, EMPTY, 25),
    ([], "Intermediate", EMPTY, 67.5),  # +10 experience, +7.5 overridden saved difficulty
    ([], None, replace(EMPTY, favorites=categories(["Strategy"])), 60),
    ([], None, replace(EMPTY, difficulty="Medium"), 57.5),
    ([], None, replace(EMPTY, playtime=60), 57.5),
    ([], None, replace(EMPTY, playtime=30), 50),
    ([], None, replace(EMPTY, playtime=15), 46.25),
])
def test_weighted_components(requested, experience, preference, expected):
    assert score_game(GAME, [preference], categories(requested), experience, group=False) == expected


def test_missing_participants_are_neutral_and_equal():
    favorite = replace(EMPTY, favorites=categories(["Strategy"]))
    assert score_game(GAME, [favorite, EMPTY], frozenset(), None, group=True) == 55
    assert score_game(GAME, [], frozenset(), None, group=True) == 50


def test_group_dislike_penalty_is_proportional_and_not_disabled_by_request():
    dislike = replace(EMPTY, dislikes=categories(["Strategy"]))
    assert score_game(GAME, [dislike, EMPTY], frozenset(), None, group=True) == 45
    # +30 requested, +10 neutral experience, +25 neutral saved, -10 half-disliked game.
    assert score_game(GAME, [dislike], categories(["Strategy"]), None, group=True) == 55
    assert personally_disliked(GAME, dislike, frozenset())
    assert not personally_disliked(GAME, dislike, categories(["Strategy"]))
    both = replace(dislike, dislikes=GAME.categories)
    assert personally_disliked(GAME, both, categories(["Strategy"]))


def test_score_bounds_and_low_scoring_games():
    favorite = SavedPreferences(GAME.categories, frozenset(), "Medium", 60)
    assert score_game(GAME, [favorite], GAME.categories, "Intermediate", group=True) == 100
    worst = SavedPreferences(categories(["Party"]), GAME.categories, "Hard", 1)
    game = replace(GAME, difficulty="Easy")
    assert score_game(game, [worst], categories(["Party"]), "Experienced", group=True) == 0
    assert score_game(replace(GAME, categories=frozenset()), [EMPTY], frozenset(), None, group=True) == 50


def test_explicit_favorites_take_precedence():
    saved = replace(EMPTY, favorites=categories(["Party"]))
    assert score_game(GAME, [saved], categories(["Strategy"]), None, group=False) == 75


def test_group_questionnaire_never_replaces_saved_preferences():
    party = GameFeatures(categories(["Party"]), "Medium", 60)
    fans = [replace(EMPTY, favorites=categories(["Party"]))] * 3
    # Request contributes 0/30; every attendee keeps their 20-point favorite match.
    assert score_game(party, fans, frozenset(), None, group=True) == 60
    assert score_game(party, fans, categories(["Strategy"]), None, group=True) == 45
    medium = [replace(EMPTY, difficulty="Medium")]
    # Beginner adds 10/20 for adjacent Easy; saved Medium keeps its full 15.
    assert score_game(party, medium, frozenset(), "Beginner", group=True) == 57.5
    # Personal mode keeps explicit-input replacement of the user's own preferences.
    assert score_game(party, medium, frozenset(), "Beginner", group=False) == 50


def test_group_participants_have_equal_influence_regardless_of_order():
    fan = replace(EMPTY, favorites=categories(["Strategy"]), difficulty="Medium")
    hater = replace(EMPTY, dislikes=categories(["Strategy", "Cooperative"]), difficulty="Hard")
    first = score_game(GAME, [fan, hater, EMPTY], frozenset(), None, group=True)
    assert first == score_game(GAME, [EMPTY, hater, fan], frozenset(), None, group=True)
    # Saved mean (42.5 + 25 + 25) / 3 plus neutral 25 request components, minus 20/3.
    assert first == pytest.approx(15 + 10 + 92.5 / 3 - 20 / 3)


def test_group_reason_reflects_net_saved_fit_and_penalty():
    like = replace(EMPTY, favorites=categories(["Strategy"]))
    hate = replace(EMPTY, dislikes=categories(["Strategy"]))
    mixed = explain(GAME, [like, hate, hate, hate], frozenset(), None, 4, 60, group=True)
    assert "Fits saved group preferences" not in mixed
    assert mixed.endswith("Some saved group preferences count against this game.")
    slow = explain(GAME, [replace(EMPTY, playtime=15)], frozenset(), None, 4, 60, group=True)
    assert slow.endswith("Some saved group preferences count against this game.")
    liked = explain(GAME, [like, EMPTY], frozenset(), None, 4, 60, group=True)
    assert liked.endswith("Fits saved group preferences.")
    neutral = explain(GAME, [EMPTY, EMPTY], frozenset(), None, 4, 60, group=True)
    assert neutral == "Supports 4 players and fits your 60-minute limit."


def test_explanations_are_stable_and_private():
    saved = SavedPreferences(GAME.categories, GAME.categories, "Medium", 60)
    reason = explain(GAME, [saved], GAME.categories, "Intermediate", 4, 60, group=True)
    # Conflicting favorites and dislikes must not be reported as a group fit.
    assert reason == ("Supports 4 players and fits your 60-minute limit. "
                      "Matches requested categories. Matches requested experience level. "
                      "Some saved group preferences count against this game.")
    assert "dislike" not in reason.lower() and "Strategy" not in reason
    personal = explain(GAME, [saved], frozenset(), None, 4, 60, group=False)
    assert "your saved favorite categories" in personal
    assert "your saved difficulty preference" in personal
