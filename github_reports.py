from contextlib import closing
import copy
import json
import re
import time
import urllib2

import hipchat_message


# How large of a change to be an anomaly?
CHANGE_THRESHOLD = 1.15
# How large of a change if rate was too small before
CHANGE_THRESHOLD_SMALL = 1.90
# The rate of reports below which we should use the higher threshold.
SMALL_RATE = 0.01 / (60 * 60)
# Non-exercise keys in the dictionary
SPECIAL_VALUES = ["elapsed_time", "max_id", "last_time"]


def get_errors(old_reports):

    stats = {}
    issues = []

    # The issue at which we should stop looking for more
    # -1 indicates we shouldn't do more than 1 page
    last_issue = old_reports.get("max_id", -1)

    # Track the number of the first issue we find this time
    first_issue = [last_issue]  # Lets us modify this from within get_issues

    def get_issues(page):
        with closing(urllib2.urlopen(
                "https://api.github.com/repos/Khan/khan-exercises/issues?page="
                + str(page) + "&per_page=100")) as issue_data:

            done = False
            for issue in json.loads(issue_data.read()):
                if issue["user"]["login"] == "KhanBugz":
                    if last_issue == -1:
                        done = True

                    if issue["number"] > last_issue:
                        first_issue[0] = max(first_issue[0], issue["number"])
                        issues.append(issue)
                    else:
                        done = True
                        break

            if ((re.findall(
                    r'<(.*?)>; rel="(.*?)"',
                    issue_data.info().getheader("Link"))[0][1] == "next")
                    and not done):
                get_issues(page + 1)

    get_issues(1)

    first_issue = first_issue[0]

    for issue in issues:
        regex_matches = re.findall(
            r'Khan:master/exercises/(.+?)\.html', issue["body"])
        if len(regex_matches) == 0:
            print issue

        exercise = regex_matches[0]
        if not exercise in stats:
            stats[exercise] = {}
            stats[exercise]["issues"] = 1
            stats[exercise]["href"] = [issue["html_url"]]
        else:
            stats[exercise]["issues"] += 1
            stats[exercise]["href"].append(issue["html_url"])

    for ex in old_reports:
        if ex not in SPECIAL_VALUES:
            old_reports[ex]["this_period"] = 0

    for ex in stats:
        if ex not in old_reports:
            old_reports[ex] = {"num_errors": 0,
                               "this_period": 0}

        old_reports[ex]["num_errors"] += stats[ex]["issues"]
        old_reports[ex]["this_period"] = stats[ex]["issues"]
        old_reports[ex]["href"] = stats[ex]["href"]

    cur_time = time.time()

    this_period = cur_time - old_reports["last_time"]

    old_reports["max_id"] = first_issue
    old_reports["elapsed_time"] += this_period
    old_reports["last_time"] = cur_time

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
        exercise_file = open(
            os.path.join(os.path.dirname(__file__), "exercise_reports"), 'r+')
        ex_reports = json.loads(exercise_file.read())
    except IOError:
        exercise_file = open(
            os.path.join(os.path.dirname(__file__), "exercise_reports"), 'w')
        ex_reports = {"elapsed_time": 1,  # Filler value
                      "max_id": -1,
                      "last_time": 0}

    new_reports = get_errors(copy.deepcopy(ex_reports))

    for ex in new_reports:
        if ex in SPECIAL_VALUES:
            continue

        if ex in ex_reports and ex_reports[ex]["num_errors"] > 0:
            old_rate = (ex_reports[ex]["num_errors"] /
                            ex_reports["elapsed_time"])
            new_rate = (new_reports[ex]["this_period"] /
                            new_reports["elapsed_time"])

            threshold = (CHANGE_THRESHOLD if old_rate > SMALL_RATE
                         else CHANGE_THRESHOLD_SMALL)

            if threshold * old_rate < new_rate:
                # Too many errors!
                hipchat_message.send_message(
                    "Elevated exercise bug report rate in exercise %s!"
                    " (Reports: %s. Rate: %.3f per hour."
                    " Normal rate: %.3f per hour."
                    " New rate is %.2f%% of normal.)"
                        % (ex, generate_links(new_reports[ex]["href"]),
                          new_rate * 60 * 60,
                          old_rate * 60 * 60,
                          (new_rate / old_rate) * 100),
                    room_id="Exercises")
        if "href" in new_reports[ex]:
            del new_reports[ex]["href"]  # don't need to keep the link around

    # Overwrite with new contents
    exercise_file.seek(0)
    exercise_file.truncate()
    exercise_file.write(json.dumps(new_reports))

    exercise_file.close()

if  __name__ == "__main__":
    main()
