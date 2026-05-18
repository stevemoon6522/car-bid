"""tests/test_matcher.py — Unit tests for matcher.py score functions and pipeline."""
import pytest
from matcher import (
    score_grade,
    score_year,
    score_mileage,
    apply_price_adjustments,
    rank_candidates,
    summarize_bids,
)


# ---------------------------------------------------------------------------
# score_grade
# ---------------------------------------------------------------------------

class TestScoreGrade:
    def test_exact_match_returns_40(self):
        assert score_grade("A", "A") == 40
        assert score_grade("B", "B") == 40
        assert score_grade("C", "C") == 40
        assert score_grade("D", "D") == 40

    def test_one_step_returns_28(self):
        assert score_grade("A", "B") == 28
        assert score_grade("B", "A") == 28
        assert score_grade("B", "C") == 28
        assert score_grade("C", "D") == 28

    def test_two_steps_returns_12(self):
        assert score_grade("A", "C") == 12
        assert score_grade("C", "A") == 12
        assert score_grade("B", "D") == 12

    def test_three_steps_returns_2(self):
        assert score_grade("A", "D") == 2
        assert score_grade("D", "A") == 2

    def test_case_insensitive(self):
        assert score_grade("a", "b") == 28
        assert score_grade("A", "b") == 28

    def test_none_row_returns_0(self):
        assert score_grade("A", None) == 0

    def test_none_input_returns_0(self):
        assert score_grade(None, "A") == 0

    def test_empty_string_returns_0(self):
        assert score_grade("", "A") == 0
        assert score_grade("A", "") == 0

    def test_invalid_grade_letter_returns_0(self):
        # F is valid in second position but not first; any non-ABCD → 0
        assert score_grade("F", "A") == 0
        assert score_grade("A", "F") == 0
        assert score_grade("E", "B") == 0
        assert score_grade("X", "X") == 0


# ---------------------------------------------------------------------------
# score_year
# ---------------------------------------------------------------------------

class TestScoreYear:
    def test_same_year_returns_40(self):
        assert score_year(2021, 2021) == 40

    def test_one_year_diff_returns_32(self):
        assert score_year(2021, 2020) == 32
        assert score_year(2020, 2021) == 32

    def test_two_year_diff_returns_24(self):
        assert score_year(2021, 2019) == 24

    def test_three_year_diff_returns_16(self):
        assert score_year(2021, 2018) == 16

    def test_four_year_diff_returns_8(self):
        assert score_year(2021, 2017) == 8

    def test_five_plus_year_diff_returns_0(self):
        assert score_year(2021, 2016) == 0
        assert score_year(2021, 2010) == 0
        assert score_year(2021, 1999) == 0

    def test_none_row_year_returns_0(self):
        assert score_year(2021, None) == 0


# ---------------------------------------------------------------------------
# score_mileage
# ---------------------------------------------------------------------------

class TestScoreMileage:
    def test_within_5pct_returns_20(self):
        assert score_mileage(100_000, 100_000) == 20   # 0% diff
        assert score_mileage(100_000, 104_999) == 20   # 4.999%
        assert score_mileage(100_000, 95_001) == 20    # 4.999%

    def test_exactly_5pct_returns_20(self):
        assert score_mileage(100_000, 105_000) == 20   # exactly 5%

    def test_within_10pct_returns_16(self):
        assert score_mileage(100_000, 109_999) == 16

    def test_exactly_10pct_returns_16(self):
        assert score_mileage(100_000, 110_000) == 16

    def test_within_20pct_returns_12(self):
        assert score_mileage(100_000, 119_999) == 12

    def test_within_30pct_returns_8(self):
        assert score_mileage(100_000, 129_999) == 8

    def test_within_40pct_returns_4(self):
        assert score_mileage(100_000, 139_999) == 4

    def test_over_40pct_returns_0(self):
        assert score_mileage(100_000, 200_000) == 0
        assert score_mileage(100_000, 0) == 0

    def test_none_row_km_returns_0(self):
        assert score_mileage(100_000, None) == 0

    def test_zero_input_km_returns_0_not_error(self):
        # guard divide-by-zero: input_km == 0 → 0
        assert score_mileage(0, 0) == 0
        assert score_mileage(0, 100_000) == 0

    def test_negative_input_km_returns_0(self):
        # C1: negative input_km must not flip sign and return a false-positive score.
        assert score_mileage(-50_000, 50_000) == 0
        assert score_mileage(-1, 0) == 0
        assert score_mileage(-100_000, 100_000) == 0


# ---------------------------------------------------------------------------
# apply_price_adjustments
# ---------------------------------------------------------------------------

class TestApplyPriceAdjustments:
    def _row(self, final_price=1500, options="", color="검정"):
        return {"final_price": final_price, "options": options, "color": color}

    def _inp(self, options="", color="검정"):
        return {"options": options, "color": color}

    def test_no_adjustments(self):
        price, reasons = apply_price_adjustments(self._row(), self._inp())
        assert price == 1500
        assert reasons == []

    def test_sunroof_in_row_not_in_input(self):
        row = self._row(options="네비,선루프,스마트키")
        inp = self._inp(options="네비,스마트키")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400
        assert len(reasons) == 1
        assert "선루프" in reasons[0]

    def test_sunroof_in_both_no_adjustment(self):
        row = self._row(options="선루프,네비")
        inp = self._inp(options="선루프")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500
        assert reasons == []

    def test_sunroof_neither_no_adjustment(self):
        price, reasons = apply_price_adjustments(self._row(options="네비"), self._inp(options="네비"))
        assert price == 1500
        assert reasons == []

    def test_white_row_nonwhite_input(self):
        row = self._row(color="흰색")
        inp = self._inp(color="검정")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400
        assert len(reasons) == 1
        assert "흰색" in reasons[0]

    def test_white_both_no_adjustment(self):
        row = self._row(color="흰색")
        inp = self._inp(color="흰색")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500
        assert reasons == []

    def test_both_adjustments_cumulative(self):
        row = self._row(options="선루프,네비", color="흰색")
        inp = self._inp(options="네비", color="검정")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1300  # -100 -100
        assert len(reasons) == 2

    def test_sunroof_substring_match_variant(self):
        # "파노라마 선루프" must still match
        row = self._row(options="파노라마 선루프,네비")
        inp = self._inp(options="네비")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400

    def test_input_has_sunroof_variant_row_does_not(self):
        # row has no sunroof, input has sunroof → no adjustment (rule is one-directional)
        row = self._row(options="네비")
        inp = self._inp(options="선루프,네비")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500
        assert reasons == []

    def test_nonwhite_row_white_input_no_adjustment(self):
        # rule is: row == white AND input != white; reverse → no adjustment
        row = self._row(color="검정")
        inp = self._inp(color="흰색")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500

    # M3: sunroof negation phrases
    def test_sunroof_negation_biseolruf_no_adjustment(self):
        # "비선루프" must NOT trigger the sunroof deduction.
        row = self._row(options="비선루프,네비")
        inp = self._inp(options="네비")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500
        assert reasons == []

    def test_sunroof_negation_eomseom_no_adjustment(self):
        # "선루프 없음" must NOT trigger the sunroof deduction.
        row = self._row(options="선루프 없음,네비")
        inp = self._inp(options="네비")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500
        assert reasons == []

    def test_panorama_sunroof_positive(self):
        # "파노라마 선루프" must trigger the deduction.
        row = self._row(options="파노라마 선루프,네비")
        inp = self._inp(options="네비")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400
        assert len(reasons) == 1

    # M4: white synonyms
    def test_white_synonym_baeksaek_triggers_adjustment(self):
        row = self._row(color="백색")
        inp = self._inp(color="검정")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400
        assert len(reasons) == 1

    def test_white_synonym_hwaite_triggers_adjustment(self):
        row = self._row(color="화이트")
        inp = self._inp(color="검정")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400

    def test_white_synonym_english_triggers_adjustment(self):
        row = self._row(color="White")
        inp = self._inp(color="검정")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1400

    def test_white_synonym_input_also_white_no_adjustment(self):
        # input is "화이트" (synonym of 흰색) — both are white, no deduction.
        row = self._row(color="흰색")
        inp = self._inp(color="화이트")
        price, reasons = apply_price_adjustments(row, inp)
        assert price == 1500
        assert reasons == []


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------

def _make_row(grade_first="B", year=2021, mileage_km=80_000, final_price=1500, options="", color="검정", **kw):
    return {
        "grade_first": grade_first,
        "year": year,
        "mileage_km": mileage_km,
        "final_price": final_price,
        "options": options,
        "color": color,
        "car_name": "K5",
        "model_name": "K5 3세대",
        "auction_date": "2025-12-01",
        "full_title": kw.get("full_title", "K5 3세대 2.0"),
        "grade": grade_first + "B",
    }


_BASE_INPUT = {
    "car_name": "K5",
    "model_name": "K5 3세대",
    "year": 2021,
    "mileage_km": 80_000,
    "grade_first": "B",
    "color": "검정",
    "options": "",
}


class TestRankCandidates:
    def test_returns_top_n(self):
        rows = [_make_row(grade_first="A") for _ in range(10)]
        result = rank_candidates(rows, _BASE_INPUT, top_n=5)
        assert len(result) == 5

    def test_sorted_by_score_desc(self):
        rows = [
            _make_row(grade_first="D", year=2015, mileage_km=200_000),  # low score
            _make_row(grade_first="B", year=2021, mileage_km=80_000),   # high score
            _make_row(grade_first="C", year=2019, mileage_km=100_000),  # mid score
        ]
        result = rank_candidates(rows, _BASE_INPUT, top_n=3)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_enriched_fields_present(self):
        result = rank_candidates([_make_row()], _BASE_INPUT)
        r = result[0]
        assert "score" in r
        assert "score_breakdown" in r
        assert "adjusted_price" in r
        assert "recommended_bid" in r
        assert "adjustment_reasons" in r

    def test_recommended_bid_is_85_pct(self):
        row = _make_row(final_price=1000)
        result = rank_candidates([row], _BASE_INPUT)
        assert result[0]["recommended_bid"] == round(1000 * 0.85)

    def test_top_n_fewer_than_available(self):
        result = rank_candidates([_make_row()], _BASE_INPUT, top_n=5)
        assert len(result) == 1

    def test_empty_rows_returns_empty(self):
        result = rank_candidates([], _BASE_INPUT)
        assert result == []

    def test_perfect_score(self):
        row = _make_row(grade_first="B", year=2021, mileage_km=80_000)
        result = rank_candidates([row], _BASE_INPUT)
        r = result[0]
        # grade B==B → 40, year 0diff → 40, mileage 0% → 20 = 100
        assert r["score"] == 100

    def test_ties_stable_order(self):
        """Tied rows with identical auction_date keep their original order (stable sort)."""
        row1 = _make_row(grade_first="B", year=2021, mileage_km=80_000, full_title="first")
        row2 = _make_row(grade_first="B", year=2021, mileage_km=80_000, full_title="second")
        result = rank_candidates([row1, row2], _BASE_INPUT)
        assert result[0]["full_title"] == "first"

    def test_ties_broken_by_recent_auction_date(self):
        """N14: when scores are equal, more recent auction_date ranks first."""
        row_old = {**_make_row(grade_first="B", year=2021, mileage_km=80_000, full_title="old"), "auction_date": "2025-01-01"}
        row_new = {**_make_row(grade_first="B", year=2021, mileage_km=80_000, full_title="new"), "auction_date": "2025-06-01"}
        result = rank_candidates([row_old, row_new], _BASE_INPUT)
        assert result[0]["full_title"] == "new"

    def test_adjustment_applied_to_recommended_bid(self):
        row = _make_row(final_price=1500, options="선루프,네비", color="흰색")
        inp = {**_BASE_INPUT, "color": "검정", "options": "네비"}
        result = rank_candidates([row], inp)
        r = result[0]
        # -100 sunroof, -100 white = adjusted 1300; recommended 1300*0.85 = 1105
        assert r["adjusted_price"] == 1300
        assert r["recommended_bid"] == round(1300 * 0.85)

    def test_no_adjustments_full_price_used(self):
        row = _make_row(final_price=2000, options="네비", color="검정")
        result = rank_candidates([row], _BASE_INPUT)
        assert result[0]["adjusted_price"] == 2000


# ---------------------------------------------------------------------------
# summarize_bids
# ---------------------------------------------------------------------------

class TestSummarizeBids:
    def test_empty_returns_empty_dict(self):
        assert summarize_bids([]) == {}

    def test_single_item(self):
        row = _make_row(final_price=1000)
        ranked = rank_candidates([row], _BASE_INPUT)
        s = summarize_bids(ranked)
        bid = round(1000 * 0.85)
        assert s["count"] == 1
        assert s["mean"] == bid
        assert s["median"] == bid
        assert s["min"] == bid
        assert s["max"] == bid

    def test_multiple_items(self):
        rows = [_make_row(final_price=p) for p in [1000, 2000, 3000]]
        ranked = rank_candidates(rows, _BASE_INPUT)
        s = summarize_bids(ranked)
        bids = [round(p * 0.85) for p in [1000, 2000, 3000]]
        assert s["min"] == min(bids)
        assert s["max"] == max(bids)
        assert s["count"] == 3
