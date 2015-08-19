import collections
import decimal
import logging
import os

import alertlib


def probability(past_errors,
                past_time,
                errors_this_period,
                time_this_period):
    """Given the number of errors we've had in the past, how long of a period
    those errors occured over, the number of errors and the length of this
    period, return the probability that we saw this number of errors due to
    an abnormally elevated rate of reports,
    as well as the mean (for displaying to users).
    """
    mean = (past_errors / past_time) * time_this_period
    return (mean, poisson_cdf(errors_this_period - 1, mean))


def poisson_cdf(actual, mean):
    """Return the probability that we see actual or anything smaller
    in a random measurement of a
    variable with a poisson distribution with mean mean.
    Expects mean to be a Decimal or a float
    (we use Decimal so that long periods and high numbers of reports work--
    a mean of 746 or higher would cause a zero to propagate and make us report
    a probability of 0 even if the actual probability was almost 1.)
    """
    if actual < 0:
        return decimal.Decimal(0)

    if isinstance(mean, float):
        mean = decimal.Decimal(mean)

    cum_prob = decimal.Decimal(0)

    p = (-mean).exp()
    cum_prob += p
    for i in xrange(actual):
        # We calculate the probability of each lesser value individually, and
        # sum as we go
        p *= mean
        p /= i + 1

        cum_prob += p

    return float(cum_prob)


def relative_path(f):
    """Given f, which is assumed to be in the same directory as this util file,
    return the relative path to it."""
    return os.path.join(os.path.dirname(__file__), f)


def thousand_commas(n):
    """Given n, a number, put in thousand separators.
    EX: thousand_commas(100000) = 100,000
        thousand_commas(1000000.0123) = 1,000,000.0123
    """
    return '{:,}'.format(n)


def merge_int_dicts(d1, d2):
    """Given two dictionaries with integer values, merge them.
    EX: merge_int_dicts({'a': 1}, {'a': 2, 'b': 5}) = {'a': 3, 'b': 5}
    """
    merged_dict = collections.defaultdict(int)
    for d in (d1, d2):
        for k in d:
            merged_dict[k] += d[k]
    return merged_dict


def send_to_hipchat(message, room_id):
    alertlib.Alert(message, html=True, severity=logging.ERROR) \
        .send_to_hipchat(room_id, sender='beep-boop')
