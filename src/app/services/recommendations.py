"""Pure, deterministic recommendation scoring; no database/session dependencies.

Five components (30/20/20/15/15) each contribute a value in [0, 1].
Missing inputs contribute neutral 0.5, keeping scores comparable across users.
Category compatibility is the fraction of desired categories present in the game.
Difficulty compatibility is 1 for exact, 0.5 for adjacent, 0 for opposite levels.
Saved playtime compatibility is min(1, preferred_playtime / game.playtime).
The explicit maximum playtime is always a hard limit, while saved playtime
remains a soft preference.
Personal mode: explicit categories replace saved favorites and override matching
dislikes; explicit experience replaces saved difficulty. Personal dislikes are a
hard filter.
Game-night mode: questionnaire categories and experience feed only their own
30/20-point components and never replace, erase, or disable any participant's
saved favorites, difficulty, playtime, or dislikes. Saved components are averaged
equally, including missing records as neutral. Group dislikes subtract up to 20
points: mean fraction of game categories disliked, even when requested.
Scores are clamped to [0, 100]; callers sort unrounded values before rounding.
"""

from dataclasses import dataclass
from collections.abc import Iterable, Sequence


DIFFICULTIES = {"Easy": 0, "Medium": 1, "Hard": 2}
EXPERIENCE = {"Beginner": "Easy", "Intermediate": "Medium", "Experienced": "Hard"}


def categories(values: Iterable[str] | None) -> frozenset[str]:
    # Stored JSON is unvalidated: ignore non-list containers and non-string items.
    if not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(value.strip().casefold() for value in values
                     if isinstance(value, str) and value.strip())


@dataclass(frozen=True)
class GameFeatures:
    categories: frozenset[str]
    difficulty: str
    playtime: int


@dataclass(frozen=True)
class SavedPreferences:
    favorites: frozenset[str] = frozenset()
    dislikes: frozenset[str] = frozenset()
    difficulty: str | None = None
    playtime: int | None = None


def category_match(game: frozenset[str], desired: frozenset[str]) -> float:
    return len(game & desired) / len(desired) if desired else 0.5


def difficulty_match(game: str, desired: str | None) -> float:
    return 0.5 if desired is None else 1 - abs(DIFFICULTIES[game] - DIFFICULTIES[desired]) / 2


def personally_disliked(game: GameFeatures, preference: SavedPreferences,
                        requested: frozenset[str]) -> bool:
    return bool(game.categories & (preference.dislikes - requested))


def saved_score(game: GameFeatures, preference: SavedPreferences,
                favorites: frozenset[str], difficulty: str | None) -> float:
    score = 20 * category_match(game.categories, favorites)
    score += 15 * difficulty_match(game.difficulty, difficulty)
    score += 15 * (min(1.0, preference.playtime / game.playtime)
                   if preference.playtime is not None else 0.5)
    return score


# Saved components of a participant without preferences: 20/15/15 at 0.5 each.
NEUTRAL_SAVED_SCORE = 25.0


def group_saved_fit(game: GameFeatures,
                    preferences: Sequence[SavedPreferences]) -> tuple[float, float]:
    """Mean saved score and mean disliked fraction, each participant weighted equally."""
    participants = preferences or [SavedPreferences()]
    saved = sum(saved_score(game, p, p.favorites, p.difficulty) for p in participants)
    penalty = sum(len(game.categories & p.dislikes) / len(game.categories)
                  if game.categories else 0.0 for p in participants)
    return saved / len(participants), penalty / len(participants)


def score_game(game: GameFeatures, preferences: Sequence[SavedPreferences],
               requested: frozenset[str], experience: str | None, *, group: bool) -> float:
    target = EXPERIENCE.get(experience)
    score = 30 * category_match(game.categories, requested)
    score += 20 * difficulty_match(game.difficulty, target)
    if group:
        saved, penalty = group_saved_fit(game, preferences)
        score += saved - 20 * penalty
    else:
        participants = preferences or [SavedPreferences()]
        score += sum(saved_score(game, p, requested or p.favorites, target or p.difficulty)
                     for p in participants) / len(participants)
    return max(0.0, min(100.0, score))


def explain(game: GameFeatures, preferences: Sequence[SavedPreferences],
            requested: frozenset[str], experience: str | None,
            player_count: int, max_playtime: int, *, group: bool) -> str:
    parts = [f"Supports {player_count} players and fits your {max_playtime}-minute limit."]
    if requested & game.categories:
        parts.append("Matches requested categories.")
    if experience and game.difficulty == EXPERIENCE[experience]:
        parts.append("Matches requested experience level.")
    if group:
        # Aggregate wording never attributes preferences to a participant, and
        # reflects the net saved fit and dislike penalty rather than any one match.
        saved, penalty = group_saved_fit(game, preferences)
        if penalty > 0 or saved < NEUTRAL_SAVED_SCORE:
            parts.append("Some saved group preferences count against this game.")
        elif saved > NEUTRAL_SAVED_SCORE:
            parts.append("Fits saved group preferences.")
    else:
        if preferences and preferences[0].favorites & game.categories and not requested:
            parts.append("Matches your saved favorite categories.")
        if preferences and not experience and preferences[0].difficulty == game.difficulty:
            parts.append("Matches your saved difficulty preference.")
    return " ".join(parts)
