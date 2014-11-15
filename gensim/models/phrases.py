#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Licensed under the GNU LGPL v2.1 - http://www.gnu.org/licenses/lgpl.html

"""
Automatically detect common phrases (multiword expressions) from a stream of documents.

The phrases are collocations (frequently co-occurring tokens). See [1]_ for the
exact formula.

For example, if your input stream (=an iterable, with each value a list of token strings) looks like:

>>> print(list(document_stream))
[[u'the', u'mayor', u'of', u'new', u'york', u'was', u'there'],
 [u'machine', u'learning', u'can', u'be', u'useful', u'sometimes'],
 ...,
]

you'd train the detector with:

>>> bigram = Phrases(document_stream)

and then transform any document (list of token strings) using the standard gensim syntax:

>>> doc = [u'the', u'mayor', u'of', u'new', u'york', u'was', u'there']
>>> print(bigram[doc])
[u'the', u'mayor', u'of', u'new_york', u'was', u'there']

(note `new_york` became a single token). As usual, you can also transform an entire
document stream using:

>>> print(list(bigram[any_document_stream]))
[[u'the', u'mayor', u'of', u'new_york', u'was', u'there'],
 [u'machine_learning', u'can', u'be', u'useful', u'sometimes'],
 ...,
]

You can also continue updating the collocation counts with new documents, by:

>>> bigram.add_vocab(new_document_stream)

These **phrase streams are meant to be used during text preprocessing, before
converting the resulting tokens into vectors using `Dictionary`**. See the
:mod:`gensim.models.word2vec` module for an example application of using phrase detection.

The detection can also be **run repeatedly**, to get phrases longer than
two tokens (e.g. `new_york_times`):

>>> trigram = Phrases(bigram[document_stream])
>>> doc = [u'the', u'new', u'york', u'times', u'is', u'a', u'newspaper']
>>> print(trigram[bigram[doc]])
[u'the', u'new_york_times', u'is', u'a', u'newspaper']

.. [1] Tomas Mikolov, Ilya Sutskever, Kai Chen, Greg Corrado, and Jeffrey Dean.
       Distributed Representations of Words and Phrases and their Compositionality.
       In Proceedings of NIPS, 2013.

"""

import logging
from collections import defaultdict

from six import iteritems, itervalues, string_types

from gensim import utils, interfaces

logger = logging.getLogger(__name__)


class Phrases(interfaces.TransformationABC):
    """
    Detect phrases, based on collected collocation counts. Adjacent words that appear
    together more frequently than expected are joined together with the `_` character.

    It can be used to generate phrases on the fly, using the `phrases[document]`
    and `phrases[corpus]` syntax.

    """
    def __init__(self, sentences=None, min_count=5, threshold=100,
                 max_vocab_size=20000000):
        """
        Initialize the model from an iterable of `sentences`. Each sentence must be
        a list of words (unicode strings) that will be used for training.

        The `sentences` iterable can be simply a list, but for larger corpora,
        consider a generator that streams the sentences directly from disk/network,
        without storing everything in RAM. See :class:`BrownCorpus`,
        :class:`Text8Corpus` or :class:`LineSentence` in the :mod:`gensim.models.word2vec`
        module for such examples.

        `min_count` ignore all words with total collected count lower than this.

        `threshold` represents a threshold for forming the phrases (higher means
        fewer phrases).

        `max_vocab_size` is the maximum size of the vocabulary. Used to control
        pruning of less common words, to keep memory under control.

        """
        if min_count <= 0:
            raise ValueError("min_count should be at least 1")

        if threshold <= 0:
            raise ValueError("threshold should be positive")

        self.min_count = min_count
        self.threshold = threshold
        self.max_vocab_size = max_vocab_size
        self.vocab = defaultdict(int)  # mapping between utf8 token => its count
        self.min_reduce = 1  # ignore any tokens with count smaller than this

        if sentences is not None:
            self.add_vocab(sentences)


    def __str__(self):
        """Get short string representation of this phrase detector."""
        return "%s<%i vocab, min_count=%s, threshold=%s, max_vocab_size=%s>" % (
            self.__class__.__name__, len(self.vocab), self.min_count,
            self.threshold, self.max_vocab_size)


    @staticmethod
    def learn_vocab(sentences, max_vocab_size):
        """Collect unigram/bigram counts from the `sentences` iterable."""
        sentence_no = -1
        total_words = 0
        logger.info("collecting all words and their counts")
        vocab = defaultdict(int)
        min_reduce = 1
        for sentence_no, sentence in enumerate(sentences):
            if sentence_no % 10000 == 0:
                logger.info("PROGRESS: at sentence #%i, processed %i words and %i word types" %
                            (sentence_no, total_words, len(vocab)))
            sentence = [utils.any2utf8(s) for s in sentence]
            for bigram in zip(sentence, sentence[1:]):
                word = bigram[0]
                bigram_word = "%s_%s" % bigram
                total_words += 1
                vocab[word] += 1
                vocab[bigram_word] += 1

            if sentence:    # add last word skipped by previous loop
                word = sentence[-1]
                vocab[word] += 1

            if len(vocab) > max_vocab_size:
                prune_vocab(vocab, min_reduce)
                min_reduce += 1

        logger.info("collected %i word types from a corpus of %i words (unigram + bigrams) and %i sentences" %
                    (len(vocab), total_words, sentence_no + 1))
        return min_reduce, vocab


    def add_vocab(self, sentences):
        """
        Merge the collected counts `vocab` into this phrase detector.

        """
        # uses a separate vocab to collect the token counts from `sentences`.
        # this consumes more RAM than merging new sentences into `self.vocab`
        # directly, but gives the new sentences a fighting chance to collect
        # sufficient counts, before being pruned out by the (large) accummulated
        # counts collected in previous learn_vocab runs.
        min_reduce, vocab = self.learn_vocab(sentences, self.max_vocab_size)

        logger.info("merging %i counts into %s" % (len(vocab), self))
        self.min_reduce = max(self.min_reduce, min_reduce)
        for word, count in iteritems(vocab):
            self.vocab[word] += count
        if len(self.vocab) > self.max_vocab_size:
            prune_vocab(self.vocab, self.min_reduce)
            self.min_reduce += 1

        logger.info("merged %s" % self)


    def __getitem__(self, doc):
        """
        Convert the input token stream `doc` (=list of unicode tokens) into
        a phrase stream (=list of unicode tokens, with detected phrases are joined by u'_').

        If `doc` is an entire corpus (documents iterable) instead of a single
        document, return an iterable that converts each of the corpus' documents,
        one after another.

        Example::

          >>> sentences = Text8Corpus(path_to_corpus)
          >>> bigram = Phrases(sentences, min_count=5, threshold=100)
          >>> for sentence in phrases[sentences]:
          ...     print(u' '.join(s))
            he refuted nechaev other anarchists sometimes identified as pacifist anarchists advocated complete
            nonviolence leo_tolstoy

        """
        try:
            is_doc = not doc or isinstance(doc[0], string_types)
        except:
            is_doc = False
        if not is_doc:
            # if the input is an entire corpus (rather than a single document),
            # return an iterable stream.
            return self._apply(doc)

        s, new_s = [utils.any2utf8(w) for w in doc], []
        last_bigram = False
        for bigram in zip(s, s[1:]):
            if all(uni in self.vocab for uni in bigram):
                bigram_word = "%s_%s" % bigram
                if bigram_word in self.vocab and not last_bigram:
                    pa = float(self.vocab[bigram[0]])
                    pb = float(self.vocab[bigram[1]])
                    pab = float(self.vocab[bigram_word])
                    score = (pab - self.min_count) / pa / pb * len(self.vocab)
                    # logger.debug("score for %s: (pab=%s - min_count=%s) / pa=%s / pb=%s * vocab_size=%s = %s",
                    #     bigram_word, pab, self.min_count, pa, pb, len(self.vocab), score)

                    if score > self.threshold:
                        new_s.append(bigram_word)
                        last_bigram = True
                        continue

            if not last_bigram:
                new_s.append(bigram[0])
            last_bigram = False

        if s:  # add last word skipped by previous loop
            last_token = s[-1]
            if last_token in self.vocab and not last_bigram:
                new_s.append(last_token)

        return [utils.to_unicode(w) for w in new_s]


def prune_vocab(vocab, min_reduce):
    """
    Remove all entries from the `vocab` dictionary with count smaller than `min_reduce`.
    Modifies `vocab` in place.

    """
    for w in list(vocab):  # make a copy of dict's keys
        if vocab[w] <= min_reduce:
            del vocab[w]


if __name__ == '__main__':
    import sys, os
    logging.basicConfig(format='%(asctime)s : %(threadName)s : %(levelname)s : %(message)s', level=logging.INFO)
    logging.info("running %s" % " ".join(sys.argv))

    # check and process cmdline input
    program = os.path.basename(sys.argv[0])
    if len(sys.argv) < 2:
        print(globals()['__doc__'] % locals())
        sys.exit(1)
    infile = sys.argv[1]

    from gensim.models.word2vec import Text8Corpus
    sentences = Text8Corpus(infile)

    # test_doc = LineSentence('test/test_data/testcorpus.txt')
    bigram = Phrases(sentences, min_count=5, threshold=100)
    for s in bigram[sentences]:
        print(utils.to_utf8(u' '.join(s)))
