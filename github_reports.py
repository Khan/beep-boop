#!/usr/bin/env python

import bisect
import contextlib
import copy
import iso8601
import json
import re
import time
import urllib2

import util

# Non-exercise keys in the dictionary
SPECIAL_VALUES = ["elapsed_time", "max_id", "last_time", "time_this_period"]

# prephantom hash, shared by all users who have yet to do anything.
# We don't want to filter reviews from prephantoms, since they might be
# different people
PREPHANTOM_HASH = 1840534623
# Regex to use for getting the user hash from the github report.
# Used in association with rate-limiting of bug reports.
USER_HASH_REGEX = re.compile("User hash: (\d+)")
# Frequency (seconds) with which one user can file bug reports
# without some being ignored
WAIT_PERIOD = 2 * 60


def get_errors(old_reports):
    stats = {}
    issues = []

    # The issue at which we should stop looking for more
    # -1 indicates we shouldn't do more than 1 page
    last_issue = old_reports.get("max_id", -1)

    # Track the number of the first issue we find this time
    first_issue = [last_issue]  # Lets us modify this from within get_issues

    def get_issues(page):
        url = ("https://api.github.com/repos/Khan/khan-exercises/issues"
               "?page=%d&per_page=100" % page)
        with contextlib.closing(urllib2.urlopen(url)) as issue_data:
            # This flag is False if we should continue to the next page of
            # issues and True if we should stop looking at more pages.
            done = False
            for issue in json.loads(issue_data.read()):
                if issue["user"]["login"] == "KhanBugz":
                    if last_issue == -1:
                        # If we have no data so far, only go one page.
                        done = True

                    if issue["number"] > last_issue:
                        first_issue[0] = max(first_issue[0], issue["number"])
                        issues.append(issue)
                    else:
                        # If we've come to an issue we already saw,
                        # don't continue to further pages or issues
                        done = True
                        break

            if ((re.findall(
                    r'<(.*?)>; rel="(.*?)"',
                    issue_data.info().getheader("Link"))[0][1] == "next") and
                    not done):
                get_issues(page + 1)

    get_issues(1)
    first_issue = first_issue[0]

    for issue in issues:
        regex_matches = re.findall(
            r'Khan:master/exercises/(.+?)\.html', issue["body"])
        if len(regex_matches) == 0:
            print issue
            continue

        user_hash = re.search(USER_HASH_REGEX, issue["body"])
        try:
            user_hash = user_hash.group(1)
        except AttributeError:
            user_hash = ""

        # We can't distinguish prephantom users from each other,
        # nor can we distinguish users with no hash. Put them all in the same,
        # non rate-limited bucket.
        if user_hash == PREPHANTOM_HASH:
            user_hash = ""

        created_at = iso8601.parse_date(issue["created_at"])
        exercise = regex_matches[0]

        if exercise not in stats:
            stats[exercise] = {}
            stats[exercise]["href"] = [issue["html_url"]]

            stats[exercise]["users"] = {user_hash: [created_at]}
        else:
            old_times = stats[exercise]["users"].get(user_hash, [])
            # Rate-limit number of bugs we count -- if someone submits
            # two bugs in a very short timeframe, only count 1 -- the rest
            # are probably bogus
            if (not user_hash or not old_times or
               abs(created_at - old_times[-1]).total_seconds > WAIT_PERIOD):
                # We keep this list sorted so that we can more quickly
                # look at the frequency with which a user submits messages
                bisect.insort(old_times, created_at)
                stats[exercise]["href"].append(issue["html_url"])
            else:
                print ("Ignoring %s because user %s has posted too frequently"
                       % (issue["html_url"], user_hash))

            stats[exercise]["users"][user_hash] = old_times

    for ex in old_reports:
        if ex not in SPECIAL_VALUES:
            old_reports[ex]["this_period"] = 0

    for ex in stats:
        if ex not in old_reports:
            old_reports[ex] = {"num_errors": 0,
                               "this_period": 0}

        users = stats[ex]["users"]
        issue_count = sum([len(users[u]) for u in users.keys()])

        old_reports[ex]["num_errors"] += issue_count
        old_reports[ex]["this_period"] = issue_count
        old_reports[ex]["href"] = stats[ex]["href"]

    cur_time = time.time()

    this_period = cur_time - old_reports["last_time"]

    old_reports["max_id"] = first_issue
    old_reports["elapsed_time"] += this_period
    old_reports["last_time"] = cur_time
    old_reports["time_this_period"] = this_period
    return old_reports


def generate_links(links):
    """Given a list of links, generate a string that can be inserted into
    a HipChat message with them."""
    html = []
    for i in xrange(len(links)):
        html.append("<a href='%s'>%d</a>" % (links[i], i + 1))

    return ", ".join(html)


def main():
    try:
        exercise_file = open(util.relative_path("exercise_reports"), 'r+')
        ex_reports = json.loads(exercise_file.read())
    except IOError:
        exercise_file = open(util.relative_path("exercise_reports"), 'w')
        ex_reports = {"elapsed_time": 1,  # Filler value
                      "max_id": -1,
                      "last_time": 0}

    new_reports = get_errors(copy.deepcopy(ex_reports))

    period_len = new_reports["time_this_period"]

    for ex in new_reports:
        if ex in SPECIAL_VALUES:
            continue

        if ex in ex_reports and ex_reports[ex]["num_errors"] > 0:
            errors_this_period = new_reports[ex]["this_period"]

            mean, probability = util.probability(ex_reports[ex]["num_errors"],
                                                 ex_reports["elapsed_time"],
                                                 errors_this_period,
                                                 period_len)

            print ("%s] TOTAL %s/%ss; %s-: %s/%ss; m=%.3f p=%.3f"
                   % (time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                      ex_reports[ex]["num_errors"], ex_reports["elapsed_time"],
                      ex_reports["last_time"],
                      errors_this_period, period_len,
                      mean, probability))

            if (probability > 0.997 and errors_this_period > 1):
                # Too many errors!
                util.send_to_hipchat(
                    "Elevated exercise bug report rate in exercise %s!"
                    " Reports: %s.  We saw %s in the last %s minutes,"
                    " while the mean indicates we should see around %s."
                    " Probability that this is abnormally elevated: %.4f."
                    % (ex,
                       generate_links(new_reports[ex]["href"]),
                       util.thousand_commas(errors_this_period),
                       util.thousand_commas(int(period_len / 60)),
                       util.thousand_commas(round(mean, 2)),
                       probability),
                    room_id="Exercises")
        if "href" in new_reports[ex].keys():
            del new_reports[ex]["href"]  # don't need to keep the links around

    del new_reports["time_this_period"]
    # Overwrite with new contents
    exercise_file.seek(0)
    exercise_file.truncate()
    exercise_file.write(json.dumps(new_reports))

    exercise_file.close()

if __name__ == "__main__":
    main()
