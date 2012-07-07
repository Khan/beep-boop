#!/Users/josh/.virtualenv/khan/bin/python
from datetime import datetime
from datetime import timedelta
import pytz
import sys
import time
from pymongo import Connection
import json
from contextlib import closing
import urllib2
import iso8601
import re
import operator
from itertools import islice


def report(length):

    start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=length)
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
    print "%s 0000Z to %s 2359Z" % (start_date.date(), end_date.date())

    db = Connection("analytics.khanacademy.org", 27017)["report"]["daily_ex_stats"]

    stats = {}

    for ex in db.find({"date": {"$gte": start_date, "$lte": end_date}, "filter_mode": "everything", "super_mode": "everything"}):
        if not ex["exercise"] in stats:
            stats[ex["exercise"]] = {}
            stats[ex["exercise"]]["problems_done"] = ex["problems"]
            stats[ex["exercise"]]["issues"] = 0
        else:
            stats[ex["exercise"]]["problems_done"] += ex["problems"]
    print len(stats)

    issues = []

    def get_issues(page):
        with closing(urllib2.urlopen(
                "https://api.github.com/repos/Khan/khan-exercises/issues?page="
                + str(page) + "&per_page=100")) as issue_data:

            done = False

            for issue in json.loads(issue_data.read()):
                if issue["user"]["login"] == "KhanBugz":
                    if iso8601.parse_date(issue["created_at"]).date() >= start_date.date() and iso8601.parse_date(issue["created_at"]).date() <= end_date.date():
                        issues.append(issue)
                    elif iso8601.parse_date(issue["created_at"]).date() < start_date.date():
                        done = True

            if re.findall(r'<(.*?)>; rel="(.*?)"', issue_data.info().getheader("Link"))[0][1] == "next" and not done:
                get_issues(page + 1)

    get_issues(1)


    for issue in issues:
        if len(re.findall(r'Khan:master/exercises/(.+?)\.html', issue["body"])) == 0:
            print issue

        exercise = re.findall(r'Khan:master/exercises/(.+?)\.html', issue["body"])[0]
        if not exercise in stats:
            stats[exercise] = {}
            stats[exercise]["problems_done"] = 0
            stats[exercise]["issues"] = 1
        else:
            stats[exercise]["issues"] += 1

    for exercise in stats:
        if stats[exercise]["problems_done"] == 0:
            stats[exercise]["rate"] = 1000
        else:
            stats[exercise]["rate"] = float(stats[exercise]["issues"]) / (stats[exercise]["problems_done"] / 1000.0)

    print "  A total of %d issues were reported. Top 20 exercises:" % (len(issues))
    print ""
    print "    Issues   Problems   Issues per"
    print "  reported       done  1k problems  Exercise"

    for exercise in islice(sorted(stats, key=lambda x: stats[x]['rate'], reverse=True), None, 20):
        if stats[exercise]["issues"] > 0:
            print "      %4d    %7d         %4.2f  %s" % (stats[exercise]["issues"], stats[exercise]["problems_done"], stats[exercise]["rate"], exercise)

print "Issue reports for yesterday:"
report(3)
print ""
print "Issue reports for the last week:"
report(7)
print ""
