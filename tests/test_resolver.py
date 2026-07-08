"""Tests for the name+context resolver.

Coverage rationale: the resolver is the chokepoint between unstructured
text and the structured entity store. Wrong resolutions silently
contaminate every downstream weight and analysis. We pin:

* Single-match success.
* Unknown-name handling.
* Multi-match disambiguation by context (house, party, state).
* Conservative ambiguity reporting when context is insufficient.
* Bureaucrat path returns ``deferred`` immediately (v0.5.0 contract).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from commoner_analyse.entities import (
    EntityStore,
    MpMembership,
    Person,
    make_entity_id,
)
from commoner_analyse.resolver import Resolver


def _build_store(*, with_two_joshis: bool = False) -> EntityStore:
    """A small in-memory store. Caller wraps with TemporaryDirectory."""
    tmp = tempfile.mkdtemp()
    store = EntityStore(Path(tmp))

    j1 = make_entity_id("Pralhad Joshi", "ls", "BJP")
    store.add_person(Person(entity_id=j1, canonical_name="Pralhad Joshi"))
    store.add_mp_membership(
        MpMembership(entity_id=j1, house="ls", term=18, party="BJP",
                     party_name="Bharatiya Janata Party", state="Karnataka")
    )

    if with_two_joshis:
        # A different Joshi in RS — same surface name, different entity.
        j2 = make_entity_id("Pralhad Joshi", "rs", "INC")
        store.add_person(Person(entity_id=j2, canonical_name="Pralhad Joshi"))
        store.add_mp_membership(
            MpMembership(entity_id=j2, house="rs", term=None, party="INC",
                         party_name="Indian National Congress", state="Maharashtra")
        )

    sitharaman = make_entity_id("Nirmala Sitharaman", "rs", "BJP")
    store.add_person(Person(entity_id=sitharaman, canonical_name="Nirmala Sitharaman"))
    store.add_mp_membership(
        MpMembership(entity_id=sitharaman, house="rs", term=None, party="BJP",
                     party_name="Bharatiya Janata Party", state="Karnataka")
    )

    return store


class ResolveSingleMatchTests(unittest.TestCase):
    def test_unique_name_resolves_with_full_confidence(self):
        store = _build_store()
        r = Resolver(store)
        result = r.resolve("Nirmala Sitharaman")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.confidence, 1.0)
        self.assertTrue(result.entity_id.startswith("PERSON_"))

    def test_honorific_variant_still_resolves(self):
        store = _build_store()
        r = Resolver(store)
        result = r.resolve("Smt. Nirmala Sitharaman")
        self.assertEqual(result.status, "resolved")

    def test_comma_reversed_form_still_resolves(self):
        store = _build_store()
        r = Resolver(store)
        result = r.resolve("Sitharaman, Smt. Nirmala")
        self.assertEqual(result.status, "resolved")


class ResolveUnknownTests(unittest.TestCase):
    def test_unknown_name_returns_unknown_status(self):
        store = _build_store()
        r = Resolver(store)
        result = r.resolve("Some Person Who Does Not Exist")
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.entity_id)

    def test_empty_input_returns_unknown(self):
        store = _build_store()
        r = Resolver(store)
        result = r.resolve("")
        self.assertEqual(result.status, "unknown")


class ResolveAmbiguousTests(unittest.TestCase):
    def test_two_matches_no_context_is_ambiguous(self):
        store = _build_store(with_two_joshis=True)
        r = Resolver(store)
        result = r.resolve("Pralhad Joshi")
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.entity_id)
        self.assertEqual(len(result.candidates), 2)

    def test_two_matches_disambiguated_by_house_and_party(self):
        store = _build_store(with_two_joshis=True)
        r = Resolver(store)
        result = r.resolve("Pralhad Joshi", context={"house": "ls", "party": "BJP"})
        self.assertEqual(result.status, "resolved")
        self.assertGreaterEqual(result.confidence, 0.66)

    def test_two_matches_with_only_partial_context_stays_ambiguous(self):
        # Without enough margin between top and runner-up, stay ambiguous.
        store = _build_store(with_two_joshis=True)
        r = Resolver(store)
        # Both Joshis match no context fields here -> tied at 0.0.
        result = r.resolve("Pralhad Joshi", context={"ministry": "education"})
        self.assertEqual(result.status, "ambiguous")

    def test_house_switch_across_terms_disambiguated_by_date(self):
        # Article 101(1): a person sits in at most one House at a time.
        # Two different, same-surname people each held an RS seat at some
        # point — one currently (2020-present), one long lapsed
        # (2004-2009). Matching "house" alone against ANY historical
        # membership ties them; the record's own date must break the tie
        # in favour of whoever's RS term was actually active then.
        tmp = tempfile.mkdtemp()
        store = EntityStore(Path(tmp))

        current_member = make_entity_id("Term Mover", "rs", "BJP")
        store.add_person(Person(entity_id=current_member, canonical_name="Term Mover"))
        store.add_mp_membership(
            MpMembership(entity_id=current_member, house="rs", term=None, party="BJP",
                         party_name="Bharatiya Janata Party", state="Karnataka",
                         start="2020-01-01", end=None)
        )

        lapsed_member = make_entity_id("Term Mover", "rs", "INC")
        store.add_person(Person(entity_id=lapsed_member, canonical_name="Term Mover"))
        store.add_mp_membership(
            MpMembership(entity_id=lapsed_member, house="rs", term=None, party="INC",
                         party_name="Indian National Congress", state="Kerala",
                         start="2004-01-01", end="2009-01-01")
        )

        r = Resolver(store)
        # Without date-based disambiguation, both candidates tie on house
        # alone and this would incorrectly stay "ambiguous".
        result = r.resolve(
            "Term Mover", context={"house": "rs", "date": "2023-01-01"}
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.entity_id, current_member)


class BureaucratPathTests(unittest.TestCase):
    def test_kind_hint_bureaucrat_returns_deferred(self):
        store = _build_store()
        r = Resolver(store)
        result = r.resolve(
            "Shri K. S. Somashekhar",
            context={"designation": "Additional Secretary", "ministry": "youth_affairs"},
            kind_hint="bureaucrat",
        )
        self.assertEqual(result.status, "deferred")
        self.assertIsNone(result.entity_id)
        self.assertTrue(result.candidates)  # carries a "deferred" reason


class ResolutionResultSerializationTests(unittest.TestCase):
    def test_to_dict_is_jsonable(self):
        import json
        store = _build_store()
        r = Resolver(store)
        result = r.resolve("Nirmala Sitharaman")
        d = result.to_dict()
        self.assertEqual(d["status"], "resolved")
        # Ensure it round-trips through json.
        round_tripped = json.loads(json.dumps(d))
        self.assertEqual(round_tripped["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
