"""Warn if the bug-report rate has increased recently, on UserVoice.

While we used to ask users to report problems on a google code issues
page, we now ask them to do so via UserVoice, at
   https://khanacademyfeedback.uservoice.com/

UserVoice categorizes 'ideas' by forum; the forum we are interested in
is "Bugs & Troubleshooting," where each "idea" is a bug report
(presumably).  Some bugs may also be filed elsewhere, such as
"Computing" for CS bugs, but we'll ignore them since a lot of the
ideas in Computing are probably enhancement suggestions and the like.
"""

import cPickle
import contextlib
import datetime
import json
import urllib2

import hipchat_message
import util

# Threshold of average to report an elevated rate
change_threshold = 1.10


USERVOICE_API_FILE = util.relative_path("uservoice.cfg")
USERVOICE_API_KEY = None     # set lazily


def _parse_time(s):
    """Convert a string of the form "YYYY/MM/DD HH:MM:SS +0000" to datetime."""
    # We could use strptime, but this is just as easy.
    (yyyy, mm, dd, HH, MM, SS) = (int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                  int(s[11:13]), int(s[14:16]), int(s[17:19]))
    return datetime.datetime(yyyy, mm, dd, HH, MM, SS)


def get_suggestions(page):
    """pages start at 1."""
    global USERVOICE_API_KEY
    if USERVOICE_API_KEY is None:
        with open(USERVOICE_API_FILE) as f:
            USERVOICE_API_KEY = f.read().strip()

    # I figured out the forum id by going to
    #    https://khanacademyfeedback.uservoice.com
    # and clicking on "Bugs & Troubleshooting" and noticing it went to
    #    .../forums/251593-bugs-troubleshooting
    #
    # NOTE: if we care about last-modified time instead of
    # creation time, we could do:
    #     &filter=updated_after&updated_after_date=YYYY-MM-DD HH:MM:SS -0000
    # instead of '&sort=newest'.
    url = ('https://khanacademyfeedback.uservoice.com/api/v1/forums/251593/'
           'suggestions.json?client=%s&page=%s&per_page=100&sort=newest'
           % (USERVOICE_API_KEY, page))

    with contextlib.closing(urllib2.urlopen(url)) as request:
        data = json.load(request)

    return data['suggestions']


def num_suggestions_between(start_time, end_time):
    """Return the number of reports created between start and end time.

    Also return the time of the oldest report seen, which is useful
    for getting an actual date-range when start_time is 0.
    """
    num_suggestions = 0
    suggestion_time = None

    for page in xrange(1, 1000):      # a maximum of 100000 bugs analyzed :-)
        suggestions = get_suggestions(page)
        if not suggestions:
            break
        for suggestion in suggestions:
            suggestion_time = _parse_time(suggestion['created_at'])
            if suggestion_time > end_time:
                continue
            elif suggestion_time <= start_time:
                # We are done, since we get the suggestions in time-order.
                break
            else:
                num_suggestions += 1
    else:
        raise RuntimeError("We really have 100000 bugs?!")

    return (num_suggestions, suggestion_time)


def main():
    try:
        google_code_file = util.relative_path("uservoice")
        with open(google_code_file) as f:
            old_data = cPickle.load(f)
    except IOError:
        old_data = {"elapsed_time": 0.0001,   # avoid a divide-by-0
                    "issue_count": 0,
                    "last_time": None,
                    }

    now = datetime.datetime.utcnow()
    (num_new_suggestions, oldest_suggestion_time) = num_suggestions_between(
        old_data["last_time"] or datetime.datetime.min, now)

    # The first time we run this, we take the starting time to be the
    # time of the first bug report, not AD 1 or whatever datetime.min() is.
    if old_data["last_time"] is None:
        old_data["last_time"] = oldest_suggestion_time

    time_this_period = (now - old_data["last_time"]).total_seconds()

    (mean, probability) = util.probability(old_data["issue_count"],
                                           old_data["elapsed_time"],
                                           num_new_suggestions,
                                           time_this_period)

    if (mean != 0 and probability > 0.99):
        # Too many errors!
        hipchat_message.send_message(
            "Elevated bug report rate on"
            " <a href='http://khanacademy.org/r/bugs'>Google"
            " code!</a>"
            " We saw %s in the last %s minutes,"
            " while the mean indicates we should see around %s."
            " Probability that this is abnormally elevated: %.4f."
            % (util.thousand_commas(num_new_suggestions),
               util.thousand_commas(int(time_this_period / 60)),
               util.thousand_commas(round(mean, 2)),
               probability))

    new_data = {"elapsed_time": old_data["elapsed_time"] + time_this_period,
                "issue_count": old_data["issue_count"] + num_new_suggestions,
                "last_time": now,
                }
    with open(google_code_file, 'w') as f:
        cPickle.dump(new_data, f)


if __name__ == "__main__":
    main()
