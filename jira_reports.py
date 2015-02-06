#!/usr/bin/env python

"""Warn if the bug-report rate has increased recently, on JIRA.

When users submit bug reports for specific items, they do so via a
modal on the page, and their responses get sent to JIRA:
    https://khanacademy.atlassian.net/
Because bug reports are linked to items, we're able to report spikes
on a per-exercise basis.
"""

import base64
import collections
import contextlib
import copy
import cPickle
import json
import time
import urllib
import urllib2

import util

# Only report if issue count exceeds threshold
THRESHOLD = 3


# Easier to use basic authentication than setup OAuth
JIRA_USER = 'KhanBugz'
JIRA_PASSWORD_FILE = util.relative_path('jira.cfg')
JIRA_PASSWORD = None     # set lazily


# Custom fields: JIRA API doesn't respect labels we give it in the UI
CREATED_FIELD = 'created'
EXERCISE_FIELD = 'customfield_10024'


# We want location-agnostic calls, so we need to account for timezones
LOCAL_GMT_OFFSET = time.mktime(time.gmtime(0))


def _parse_time(s):
    """Convert a string of the form "YYYY-MM-DDTHH:MM:SS.000ZZZZZ" to time_t.
    """
    # We could use strptime, but this is just as easy.
    (yyyy, mm, dd, HH, MM, T) = (int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                 int(s[11:13]), int(s[14:16]), int(s[23:26]))

    # We want this to be the number of seconds since the epoch, so we have to
    # add the timezone offset. Note that `mktime` returns local time, so we
    # also have to get rid of any machine-specific offset.
    offset = T * 60 * 60 + LOCAL_GMT_OFFSET
    return time.mktime((yyyy, mm, dd, HH, MM, 0, 0, 0, -1)) - offset


def get_ticket_data(start_time_t):
    global JIRA_PASSWORD
    if JIRA_PASSWORD is None:
        with open(JIRA_PASSWORD_FILE) as f:
            JIRA_PASSWORD = f.read().strip()

    # Compose API call: get as many issues as possible from > start_time_t
    # We can only get 1000 at a time, according to
    #   https://confluence.atlassian.com/display/CLOUDKB/Changing+maxResults+Parameter+for+JIRA+REST+API
    # Also note that we must pass in an integer representing milliseconds
    # since the epoch, according to:
    #   https://confluence.atlassian.com/display/JIRA/Advanced+Searching#AdvancedSearching-Created
    fields = ','.join([CREATED_FIELD, EXERCISE_FIELD])
    values = {'fields': fields,
              'maxResults': 1000,
              'project': '"Assessment items"'
                         ' and "Issue type" != "Not translated"'
                         ' and created > %s'
                         ' order by created asc'
                         % int(1000 * start_time_t),
              }
    url = ('https://khanacademy.atlassian.net/rest/api/latest/search'
           '?jql=%s' % urllib.urlencode(values))
    request = urllib2.Request(url)
    # Send base64-encoded 'user:password', according to
    #   https://developer.atlassian.com/display/JIRADEV/JIRA+REST+API+Example+-+Basic+Authentication
    encoded_password = base64.standard_b64encode('%s:%s' % (JIRA_USER,
                                                            JIRA_PASSWORD))
    request.add_unredirected_header('Authorization',
                                    'Basic %s' % encoded_password)
    request.add_header('Content-Type', 'application/json')
    with contextlib.closing(urllib2.urlopen(request)) as r:
        return json.load(r)


def num_tickets_between(start_time_t, end_time_t):
    num_tickets = collections.defaultdict(int)
    oldest_ticket_time_t = {}

    while start_time_t < end_time_t:
        ticket_data = get_ticket_data(start_time_t)
        if not ticket_data or not ticket_data['issues']:
            break

        for ticket in ticket_data['issues']:
            ticket_time_t = _parse_time(ticket['fields']['created'])
            if ticket_time_t > end_time_t or ticket_time_t <= start_time_t:
                continue
            # Exercise type comes as a list (should be a list of one item)
            for exercise_type in ticket['fields'][EXERCISE_FIELD]:
                num_tickets[exercise_type] += 1

                # See if we're the oldest ticket for this exercise
                if (not exercise_type in oldest_ticket_time_t or
                        oldest_ticket_time_t[exercise_type] > ticket_time_t):
                    oldest_ticket_time_t[exercise_type] = ticket_time_t

        # Tickets are ordered by time of creation (ascending), so last ticket
        # is most recent.

        # The JIRA API only has per-minute granularity, but issues returned
        # have per-second granularity. We add 60 seconds to most recent ticket
        # to avoid an infinite loop (we could keep getting the same ticket
        # over and over through rounding problems).
        start_time_t = int(_parse_time(ticket['fields']['created'])) + 60

    return (num_tickets, oldest_ticket_time_t)


def main():
    try:
        jira_status_file = util.relative_path('jira')
        with open(jira_status_file) as f:
            old_data = cPickle.load(f)
    except IOError:
        old_data = {'elapsed_times': {},
                    'ticket_counts': collections.defaultdict(int),
                    'last_time_t': None,
                    }

    # We compare the number of tickets in the last few minutes against
    # the historical average for all time. But we don't start "all
    # time" at AD 1, we start it 100 days ago.
    # Note: this is a way wider window than we use for Zendesk, but we're
    # making exercise-specific recommendations, so we need more data.
    now = int(time.time())
    num_days_in_past = 100
    (num_new_tickets, oldest_ticket_time_t) = num_tickets_between(
        old_data['last_time_t'] or (now - 86400 * num_days_in_past), now)

    # Elapsed time is computed per-exercise, so store values as we go.
    # We use a copy so that exercises that don't appear as new tickets still
    # have their old elapsed times preserved.
    elapsed_times = copy.copy(old_data['elapsed_times'])
    for exercise in num_new_tickets:
        # If this is the first time we're running, we don't have a last_time_t,
        # so we take the oldest ticket for each exercise as its last_time_t
        last_time_t = old_data['last_time_t'] or oldest_ticket_time_t[exercise]
        time_this_period = now - last_time_t
        # Avoid divide-by-0 if this is the first time we've seen an exercise
        time_last_period = old_data['elapsed_times'].get(exercise, 0.0001)

        num_old_tickets_for_exercise = old_data['ticket_counts'][exercise]
        num_new_tickets_for_exercise = num_new_tickets[exercise]
        (mean, probability) = util.probability(num_old_tickets_for_exercise,
                                               time_last_period,
                                               num_new_tickets_for_exercise,
                                               time_this_period)

        print('%s] %s TOTAL %s/%ss; %s-: %s/%ss; m=%.3f p=%.3f'
              % (time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                  exercise,
                  num_old_tickets_for_exercise, int(time_last_period),
                  last_time_t,
                  num_new_tickets_for_exercise, time_this_period,
                  mean, probability))

        if (mean != 0 and probability > 0.9995 and
                num_new_tickets_for_exercise > THRESHOLD):
            util.send_to_hipchat(
                'Elevated bug report rate on exercise \'%s\'!'
                ' We saw %s in the last %s minutes,'
                ' while the mean indicates we should see around %s.'
                ' Probability that this is abnormally elevated: %.4f.'
                % (exercise,
                   util.thousand_commas(num_new_tickets_for_exercise),
                   util.thousand_commas(int(time_this_period / 60)),
                   util.thousand_commas(round(mean, 2)),
                   probability),
                room_id='jira-monitoring')
        elapsed_times[exercise] = time_last_period + time_this_period

    new_ticket_counts = util.merge_int_dicts(old_data['ticket_counts'],
                                             num_new_tickets)
    new_data = {'elapsed_times': elapsed_times,
                'ticket_counts': new_ticket_counts,
                'last_time_t': now,
                }
    with open(jira_status_file, 'w') as f:
        cPickle.dump(new_data, f)

if __name__ == '__main__':
    main()
