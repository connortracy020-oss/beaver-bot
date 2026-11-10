"""The verifier against fake model outputs: good answers pass, anything not backed by the chunks is discarded."""
import json
import unittest

from assistant.verify import verify

CHUNKS = {
    101: "Annual Commuter Parking Permit Prices:\nZone | Price\nA (1, 2, 3) | $826\nB (1, 2, 3) | $575\nC | $167",
    102: "Permits are required year-round, Monday through Friday, 7 a.m. to 5 p.m. in A, B and C zones on campus "
         "and any ADA spaces. Permits are required at all times in any other location.",
    103: "Payment plans are available for current students. Payment plans are subject to a “$15.00 plan "
         "enrollment fee” – see mybill.oregonstate.edu.",
}


def out(answer, citations, status="answered"):
    return json.dumps({"status": status, "answer": answer, "citations": citations})


class Passes(unittest.TestCase):
    def test_exact_quotes_pass(self):
        v = verify(out("An annual A-zone permit costs $826 [1]; permits are needed weekdays 7 a.m. to 5 p.m. [2].",
                       [{"chunk_id": 101, "quote": "A (1, 2, 3) | $826"},
                        {"chunk_id": 102, "quote": "Monday through Friday, 7 a.m. to 5 p.m."}]), CHUNKS)
        self.assertTrue(v.ok, v.problems)
        self.assertEqual([c["chunk_id"] for c in v.citations], [101, 102])
        self.assertEqual(v.flags, [])

    def test_whitespace_quote_marks_and_dashes_are_normalized(self):
        # The page has curly quotes, an en dash and a line break; the model wrote plain ASCII on one line.
        v = verify(out("There is a $15 fee [1].",
                       [{"chunk_id": 103, "quote": 'subject to a "$15.00 plan enrollment fee" - see'}]), CHUNKS)
        self.assertTrue(v.ok, v.problems)

    def test_quote_may_skip_words_with_an_ellipsis_in_order(self):
        v = verify(out("Permits are needed in A, B and C zones [1].",
                       [{"chunk_id": 102, "quote": "Permits are required year-round ... in A, B and C zones"}]), CHUNKS)
        self.assertTrue(v.ok, v.problems)

    def test_json_in_a_code_fence_is_accepted(self):
        raw = "```json\n" + out("C zone is $167 [1].", [{"chunk_id": 101, "quote": "C | $167"}]) + "\n```"
        self.assertTrue(verify(raw, CHUNKS).ok)

    def test_numeric_chunk_id_as_string_is_accepted(self):
        v = verify(out("C zone is $167 [1].", [{"chunk_id": "101", "quote": "C | $167 "}]), CHUNKS)
        self.assertTrue(v.ok, v.problems)

    def test_unused_citation_is_flagged_not_discarded(self):
        v = verify(out("C zone is $167 [1].", [{"chunk_id": 101, "quote": "C | $167"},
                                              {"chunk_id": 102, "quote": "Permits are required at all times"}]), CHUNKS)
        self.assertTrue(v.ok, v.problems)
        self.assertEqual(len(v.flags), 1)


class Discarded(unittest.TestCase):
    def assertDiscarded(self, raw, why):
        v = verify(raw, CHUNKS)
        self.assertFalse(v.ok)
        self.assertTrue(any(why in p for p in v.problems), v.problems)
        return v

    def test_not_json(self):
        self.assertDiscarded("The A zone permit is $826.", "not the JSON")

    def test_prose_around_the_json(self):
        self.assertDiscarded("Here you go: " + out("$167 [1]", [{"chunk_id": 101, "quote": "C | $167"}]), "not the JSON")

    def test_not_found_is_reported_as_such(self):
        v = verify(out("", [], status="not_found"), CHUNKS)
        self.assertFalse(v.ok)
        self.assertEqual(v.status, "not_found")

    def test_unknown_status(self):
        self.assertDiscarded(out("maybe [1]", [{"chunk_id": 101, "quote": "C | $167"}], status="probably"),
                             "unknown status")

    def test_no_citations(self):
        self.assertDiscarded(out("The A zone permit is $826.", []), "no citations")

    def test_chunk_the_model_was_not_given(self):
        self.assertDiscarded(out("Permits cost $826 [1].", [{"chunk_id": 999, "quote": "A (1, 2, 3) | $826"}]),
                             "wasn't given")

    def test_fabricated_quote(self):
        self.assertDiscarded(out("Parking is free on weekends [1].",
                                 [{"chunk_id": 102, "quote": "Parking is free on weekends"}]), "not in chunk 102")

    def test_paraphrase_is_not_a_quote(self):
        self.assertDiscarded(out("Permits are needed Monday to Friday [1].",
                                 [{"chunk_id": 102, "quote": "Permits are needed Monday to Friday, 7 a.m. to 5 p.m."}]),
                             "not in chunk")

    def test_quote_from_the_wrong_chunk(self):
        self.assertDiscarded(out("A zone is $826 [1].", [{"chunk_id": 102, "quote": "A (1, 2, 3) | $826"}]),
                             "not in chunk 102")

    def test_quote_too_short_to_check(self):
        self.assertDiscarded(out("Yes [1].", [{"chunk_id": 102, "quote": "Permits"}]), "too short")

    def test_ellipsis_pieces_out_of_order(self):
        self.assertDiscarded(out("Zones [1].", [{"chunk_id": 102, "quote": "in A, B and C zones ... Permits are required year-round"}]),
                             "not in chunk")

    def test_answer_without_markers(self):
        self.assertDiscarded(out("C zone is $167.", [{"chunk_id": 101, "quote": "C | $167"}]), "cites no source")

    def test_marker_without_a_citation(self):
        self.assertDiscarded(out("C zone is $167 [1] and A is $826 [2].", [{"chunk_id": 101, "quote": "C | $167"}]),
                             "marker [2]")

    def test_invented_amount(self):
        # The quote is real, but the answer states a price that isn't on the page.
        self.assertDiscarded(out("An A-zone permit costs $900 [1].", [{"chunk_id": 101, "quote": "A (1, 2, 3) | $826"}]),
                             "number 900")

    def test_number_only_in_an_uncited_chunk(self):
        self.assertDiscarded(out("Permits are needed 7 a.m. to 5 p.m. and cost $826 [1].",
                                 [{"chunk_id": 102, "quote": "Monday through Friday, 7 a.m. to 5 p.m."}]), "number 826")

    def test_malformed_citation(self):
        self.assertDiscarded(out("C zone is $167 [1].", [{"chunk_id": 101}]), "needs an integer chunk_id")

    def test_one_bad_citation_discards_the_whole_answer(self):
        v = self.assertDiscarded(out("A is $826 [1]; parking is free on Sundays [2].",
                                     [{"chunk_id": 101, "quote": "A (1, 2, 3) | $826"},
                                      {"chunk_id": 102, "quote": "parking is free on Sundays"}]), "not in chunk 102")
        self.assertEqual(len(v.citations), 1)  # the good one was checked, but the answer is still not shown


if __name__ == "__main__":
    unittest.main()
