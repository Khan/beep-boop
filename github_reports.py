#!/Users/josh/.virtualenv/khan/bin/python
from contextlib import closing
import copy
from datetime import datetime
from datetime import timedelta
import iso8601
import json
import re
import urllib2

import hipchat_message


change_threshold = 0.10  # How large of a change to be an anomaly?


def get_errors(old_reports):

    stats = {}
    issues = []

    try:
        last_issue = old_reports["max_id"]
    except:
        last_issue = -1  # Indicates we shouldn't do more than 1 page

    first_issue = [last_issue]  # Weird hack because python and closures are :(

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

            if re.findall(r'<(.*?)>; rel="(.*?)"', issue_data.info().getheader("Link"))[0][1] == "next" and not done:
                get_issues(page + 1)

    get_issues(1)

    first_issue = first_issue[0]

    for issue in issues:
        if len(re.findall(r'Khan:master/exercises/(.+?)\.html', issue["body"])) == 0:
            print issue

        exercise = re.findall(r'Khan:master/exercises/(.+?)\.html', issue["body"])[0]
        if not exercise in stats:
            stats[exercise] = {}
            stats[exercise]["issues"] = 1
        else:
            stats[exercise]["issues"] += 1

    print "A total of %d issues were reported." % (len(issues))
    for ex in old_reports:
        if ex != "max_id":
            old_reports[ex]["this_period"] = 0
            old_reports[ex]["num_periods"] += 1

    for ex in stats:
        if ex not in old_reports:
            old_reports[ex] = {"num_errors": 0,
                               "num_periods": 1,
                               "this_period": 0}

        old_reports[ex]["num_errors"] += stats[ex]["issues"]
        old_reports[ex]["this_period"] = stats[ex]["issues"]

    old_reports["max_id"] = first_issue

    return old_reports

try:
    exercise_file = open("exercise_reports", 'r+')
    ex_reports = json.loads(exercise_file.read())
except IOError:
    exercise_file = open("exercise_reports", 'w')
    ex_reports = {}


new_reports = get_errors(copy.deepcopy(ex_reports))

for ex in new_reports:
    if ex == "max_id":
        continue
    if ex in ex_reports and ex_reports[ex]["num_errors"] != 0:
        old_rate = ex_reports[ex]["num_errors"]/ex_reports[ex]["num_periods"]
        if old_rate + change_threshold * old_rate < new_reports[ex]["this_period"]:
            # Too many errors!
            print "Sending message!"
            hipchat_message.message_ones_and_zeros("Elevated exercise bug report rate in exercise %s!" %ex)

# Overwrite with new contents
exercise_file.seek(0)
exercise_file.truncate()
exercise_file.write(json.dumps(new_reports))

exercise_file.close()
