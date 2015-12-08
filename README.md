beep-boop
=========

This script monitors our Zendesk and Jira accounts and notifies us in a Slack
room when the bug report rates are far enough above the mean rate to have a very
high probability of being due to an abnormal event (think a newly introduced
bug).

"Far enough above" is given by a Poisson distribution with a certain probability
threshold -- if the probability of seeing at least this number of bug reports
due to random chance is low enough, we send a notification, because it's likely
that this elevated rate is due to a bug.

This uses [alertlib] (a sub-repo) to talk to Slack. alertlib requires being able
to import a file called `secrets.py` with the contents:

    slack_alertlib_webhook_url = "<slack url value>"

The script runs as a cron job on toby; see the aws-config repo for the crontab.

[alertlib]: https://github.com/khan/alertlib
