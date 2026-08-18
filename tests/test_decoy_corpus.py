"""Decoy corpus uniqueness regressions."""

import random

from obfush.utils.decoy_corpus import DecoyCorpus


def test_all_decoy_text_is_unique_within_run():
    corpus = DecoyCorpus(random.Random(42))
    generated = []
    for _ in range(1000):
        generated.append(corpus.generate_comment())
        generated.append(corpus.generate_inline_comment())
        generated.append(corpus.generate_log_message())

    assert len(generated) == len(set(generated))
