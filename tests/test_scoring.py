"""The overall score.

This is the number that gets read out loud, and until these tests existed the
suite never exercised a weight other than 1.0 or a model response that did not
line up exactly with the rubric. Both of those produced a wrong number silently.
"""

import pytest

from server import _overall_score, _norm_category


def rubric(*pairs):
    return {"categories": [{"name": n, "description": n, "weight": w} for n, w in pairs]}


FOUR_EQUAL = rubric(
    ("Real-World Impact", 1.0),
    ("Innovation & Creativity", 1.0),
    ("Technical Execution", 1.0),
    ("Presentation & Vision", 1.0),
)


def scores(*pairs):
    return [{"category": c, "score": s, "rationale": ""} for c, s in pairs]


class TestTheStraightforwardCase:
    def test_all_categories_all_equal_weights(self):
        got, unmatched = _overall_score(
            scores(("Real-World Impact", 5), ("Innovation & Creativity", 3),
                   ("Technical Execution", 4), ("Presentation & Vision", 2)),
            FOUR_EQUAL,
        )
        assert got == 3.5
        assert unmatched == []

    def test_full_marks_is_the_top_of_the_scale(self):
        got, _ = _overall_score(
            scores(("Real-World Impact", 5), ("Innovation & Creativity", 5),
                   ("Technical Execution", 5), ("Presentation & Vision", 5)),
            FOUR_EQUAL,
        )
        assert got == 5.0


class TestWeights:
    """The README documents weight 2.0 as the way to double a category's pull.
    Nothing tested it, so nothing would have caught it breaking."""

    def test_a_doubled_category_pulls_twice_as_hard(self):
        r = rubric(("Impact", 2.0), ("Polish", 1.0))
        # 5 on the doubled one, 2 on the other: (5*2 + 2*1) / 3
        got, _ = _overall_score(scores(("Impact", 5), ("Polish", 2)), r)
        assert got == pytest.approx(4.0)

    def test_weights_that_do_not_sum_to_the_category_count(self):
        r = rubric(("A", 0.5), ("B", 0.25), ("C", 0.25))
        got, _ = _overall_score(scores(("A", 4), ("B", 2), ("C", 2)), r)
        assert got == pytest.approx(3.0)

    def test_a_missing_weight_defaults_to_one(self):
        r = {"categories": [{"name": "A"}, {"name": "B", "weight": 1.0}]}
        got, _ = _overall_score(scores(("A", 4), ("B", 2)), r)
        assert got == pytest.approx(3.0)


class TestTheModelDoesNotAlwaysReturnWhatWasAsked:
    """The regression these guard: the denominator used to be the sum of every
    rubric weight while the numerator only covered what came back."""

    def test_an_omitted_category_does_not_deflate_the_score(self):
        # Full marks on the three that were judged. The old arithmetic divided
        # by four and reported 3.75.
        got, unmatched = _overall_score(
            scores(("Real-World Impact", 5), ("Innovation & Creativity", 5),
                   ("Technical Execution", 5)),
            FOUR_EQUAL,
        )
        assert got == 5.0
        assert unmatched == []

    def test_an_invented_category_cannot_exceed_the_scale(self):
        # The old arithmetic returned 6.25 on a rubric whose maximum is 5.
        got, unmatched = _overall_score(
            scores(("Real-World Impact", 5), ("Innovation & Creativity", 5),
                   ("Technical Execution", 5), ("Presentation & Vision", 5),
                   ("Bonus Points", 5)),
            FOUR_EQUAL,
        )
        assert got == 5.0
        assert unmatched == ["Bonus Points"]

    def test_an_invented_category_is_named_not_swallowed(self):
        _, unmatched = _overall_score(
            scores(("Real-World Impact", 4), ("Vibes", 5)), FOUR_EQUAL
        )
        assert unmatched == ["Vibes"]

    def test_nothing_matching_the_rubric_is_an_error_not_a_number(self):
        with pytest.raises(ValueError) as exc:
            _overall_score(scores(("Vibes", 5), ("Energy", 4)), FOUR_EQUAL)
        assert "Vibes" in str(exc.value)

    def test_no_scores_at_all_is_an_error(self):
        with pytest.raises(ValueError):
            _overall_score([], FOUR_EQUAL)


class TestNameMatching:
    """The model retypes the category name rather than echoing an id."""

    def test_case_does_not_matter(self):
        got, unmatched = _overall_score(scores(("real-world impact", 4)),
                                        rubric(("Real-World Impact", 1.0)))
        assert got == 4.0 and unmatched == []

    def test_spacing_does_not_matter(self):
        got, unmatched = _overall_score(scores(("Technical   Execution", 4)),
                                        rubric(("Technical Execution", 1.0)))
        assert got == 4.0 and unmatched == []

    def test_surrounding_whitespace_does_not_matter(self):
        got, _ = _overall_score(scores(("  Impact  ", 4)), rubric(("Impact", 1.0)))
        assert got == 4.0

    def test_norm_handles_none(self):
        assert _norm_category(None) == ""


class TestExportFilenamesAreUnique:
    """The bundle wrote each team's transcript, review, PRFAQ and audio by a
    slug of their name. Two teams whose names reduce to the same slug meant the
    second overwrote the first, and then received the first team's documents in
    their folder."""

    def _slugs(self, *names):
        from server import _unique_slugs
        subs = [{"id": str(i), "team_name": n} for i, n in enumerate(names)]
        return list(_unique_slugs(subs).values())

    def test_distinct_names_are_unchanged(self):
        assert self._slugs("Alpha", "Beta") == ["alpha", "beta"]

    def test_the_first_team_keeps_the_clean_name(self):
        assert self._slugs("Alpha Team", "alpha team") == ["alpha_team", "alpha_team-2"]

    def test_a_separator_difference_still_separates(self):
        assert self._slugs("Alpha/Team", "Alpha Team") == ["alpha_team", "alpha_team-2"]

    def test_three_way_collisions_keep_counting(self):
        assert self._slugs("A B", "a  b", "A/B") == ["a_b", "a_b-2", "a_b-3"]

    def test_names_that_reduce_to_nothing_do_not_collide(self):
        # Both fall back to "team".
        assert self._slugs("!!!", "???") == ["team", "team-2"]

    def test_every_submission_gets_an_entry(self):
        from server import _unique_slugs
        subs = [{"id": f"s{i}", "team_name": "Same"} for i in range(5)]
        slugs = _unique_slugs(subs)
        assert len(slugs) == 5
        assert len(set(slugs.values())) == 5
        assert set(slugs) == {f"s{i}" for i in range(5)}
