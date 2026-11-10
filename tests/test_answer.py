"""The answer pipeline with fake retrieval and fake model outputs: guard, redaction, crisis, refusal, verification.
No database, no network."""
import json
import os
import unittest
from unittest import mock

from assistant import answer as A
from assistant import providers as P
from assistant.retrieve import Hit


def hit(cid, text, url="https://registrar.oregonstate.edu/change-grading-basis", title="Change of Grading Basis",
        coverage=1.0):
    return Hit(chunk_id=cid, score=10.0, coverage=coverage, title=title, heading_path=title, url=url, page_url=url,
               retrieved_at="2026-10-22", office="Office of the Registrar", excerpt=text[:80], text=text)


HITS = [hit(7, "Step 1 Access the online Change of Grading Basis form. Step 4 Submit the form. This starts the "
               "signature routing process to your academic advisor for review and approval."),
        hit(8, "S/U grades carry no grade points and are not included in the grade point average (GPA) calculation.")]
GOOD = json.dumps({"status": "answered",
                   "answer": "Submit the online Change of Grading Basis form; your advisor reviews it [1]. "
                             "S/U grades don't count in your GPA [2].",
                   "citations": [{"chunk_id": 7, "quote": "This starts the signature routing process to your academic advisor"},
                                 {"chunk_id": 8, "quote": "S/U grades carry no grade points"}]})


def run(question, outputs, hits=HITS):
    prov = P.ScriptedProvider(outputs)
    return A.answer(question, provider=prov, search_fn=lambda q, k: hits), prov


class Guard(unittest.TestCase):
    def test_declines_with_the_right_reason(self):
        cases = {
            "What's my current student account balance?": "own_records",
            "what is my GPA right now": "own_records",
            "Do I have any holds?": "own_records",
            "What's the email address of my CS 261 instructor?": "individual_contact",
            "professor smith's phone number?": "individual_contact",
            "How many seats are left in MTH 251 this term?": "live_data",
            "is the class full": "live_data",
            "Can you write my WR 121 essay for me?": "academic_integrity",
            "do my calculus homework for me": "academic_integrity",
        }
        for q, kind in cases.items():
            res, prov = run(q, [GOOD])
            with self.subTest(q=q):
                self.assertEqual((res.kind, res.reason), ("refusal", kind))
                self.assertEqual(prov.calls, [])  # the model is never asked
                self.assertTrue(res.text)

    def test_policy_questions_are_not_declined(self):
        for q in ["Can my parents see my grades?", "How do I take my exam with DAS?",
                  "What is the Registrar's office email?", "How do I change a class to S/U grading?",
                  "How much does an official transcript cost?"]:
            with self.subTest(q=q):
                self.assertIsNone(A.guard(q))

    def test_balance_question_points_to_student_accounts(self):
        res = A.guard("How much do I owe on my bill?")
        self.assertIn("https://finance.oregonstate.edu/student-accounts", [u for _, u in res.contacts])

    def test_seat_question_links_the_schedule_of_classes(self):
        res = A.guard("how many seats are open in CS 162")
        self.assertEqual(res.contacts, [("Schedule of Classes", "https://classes.oregonstate.edu/")])


class Crisis(unittest.TestCase):
    def test_crisis_comes_before_everything_else(self):
        res, prov = run("I want to die and I can't do my homework", [GOOD])
        self.assertEqual(res.kind, "crisis")
        self.assertIn("911", res.text)
        self.assertEqual(res.contacts[0][1], "https://counseling.oregonstate.edu/crisis-resources")
        self.assertEqual(prov.calls, [])


class Redaction(unittest.TestCase):
    def test_contact_details_and_ids_are_removed(self):
        q = "I'm 932123456, email jane.doe@gmail.com or (541) 555-1234, SSN 123-45-6789. How do I drop?"
        r = A.redact(q)
        for secret in ("932123456", "jane.doe@gmail.com", "555-1234", "123-45-6789"):
            self.assertNotIn(secret, r)
        self.assertIn("How do I drop?", r)

    def test_course_numbers_and_years_survive(self):
        self.assertEqual(A.redact("Is CS 261 offered in winter 2027?"), "Is CS 261 offered in winter 2027?")

    def test_the_model_only_sees_the_redacted_question_and_page_text(self):
        res, prov = run("My ID is 931234567. How do I change to S/U grading?", [GOOD])
        system, user = prov.calls[0]
        self.assertNotIn("931234567", user)
        self.assertIn("[ID number removed]", user)
        self.assertIn('<chunk id="7"', user)
        self.assertEqual(system, A.SYSTEM)


class Pipeline(unittest.TestCase):
    def test_verified_answer_is_returned_with_sources(self):
        res, _ = run("How do I change to S/U grading?", [GOOD])
        self.assertEqual(res.kind, "answer", res.problems)
        self.assertEqual([s["n"] for s in res.sources], [1, 2])
        self.assertEqual(res.sources[0]["url"], HITS[0].url)
        self.assertEqual(res.sources[0]["retrieved_at"], "2026-10-22")
        self.assertIn("Sources:", res.render())

    def test_fabricated_answer_becomes_a_refusal(self):
        bad = json.dumps({"status": "answered", "answer": "You can switch to S/U until week 10 [1].",
                          "citations": [{"chunk_id": 7, "quote": "You can switch to S/U until week 10"}]})
        res, _ = run("How do I change to S/U grading?", [bad])
        self.assertEqual((res.kind, res.reason), ("refusal", "failed verification"))
        self.assertTrue(res.problems)
        self.assertNotIn("week 10", res.render())  # the unverified claim never reaches the student
        self.assertIn("https://registrar.oregonstate.edu/contact-us", [u for _, u in res.contacts])

    def test_model_not_found_becomes_a_refusal(self):
        res, _ = run("How do I change to S/U grading?", [json.dumps({"status": "not_found", "answer": "", "citations": []})])
        self.assertEqual((res.kind, res.reason), ("refusal", "model found no answer"))
        self.assertTrue(res.text.startswith("I couldn't find this"))

    def test_weak_retrieval_refuses_without_calling_the_model(self):
        weak = [hit(9, "Unrelated text about parking.", coverage=0.2)]
        res, prov = run("What is the airspeed of an unladen swallow?", [GOOD], hits=weak)
        self.assertEqual((res.kind, res.reason), ("refusal", "weak retrieval"))
        self.assertEqual(prov.calls, [])
        self.assertEqual(res.contacts, A.GENERAL_CONTACT)  # no office guessed from irrelevant pages

    def test_no_results_refuses(self):
        res, prov = run("How do I register for classes?", [GOOD], hits=[])
        self.assertEqual(res.reason, "weak retrieval")
        self.assertIn("Office of the Registrar", res.contacts[0][0])  # from the question's own words

    def test_extractive_provider_output_passes_the_verifier(self):
        res = A.answer("How do I change to S/U grading?", provider=P.ExtractiveProvider(),
                       search_fn=lambda q, k: HITS)
        self.assertEqual(res.kind, "answer", res.problems)


class Providers(unittest.TestCase):
    def test_paid_provider_needs_the_owners_approval(self):
        class Paid:
            name, paid = "paid-test", True

            def complete(self, system, user, max_tokens=2000):
                raise AssertionError("must not be called")

        with mock.patch.dict(P.REGISTRY, {"paid-test": Paid}), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASSISTANT_ALLOW_PAID_CALLS", None)
            with self.assertRaises(P.PaidCallNotApproved):
                P.get_provider("paid-test")
            os.environ["ASSISTANT_ALLOW_PAID_CALLS"] = "yes"
            self.assertEqual(P.get_provider("paid-test").name, "paid-test")

    def test_default_provider_is_offline(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASSISTANT_PROVIDER", None)
            prov = P.get_provider()
        self.assertEqual(prov.name, "extractive")
        self.assertFalse(prov.paid)

    def test_unknown_provider(self):
        with self.assertRaises(KeyError):
            P.get_provider("nope")


if __name__ == "__main__":
    unittest.main()
