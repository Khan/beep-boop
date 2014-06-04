import decimal
import os


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
    n = str(n)
    n = n.split(".")  # Separate stuff after the decimal point

    if len(n[0]) > 3:
        n[0] = thousand_commas(n[0][:-3]) + "," + n[0][-3:]

    return ".".join(n)
