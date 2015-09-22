#!/usr/bin/env python

"""Warn if the bug-report rate has increased recently, on Zendesk.

While we used to ask users to report problems on a google code issues
page, and then UserVoice, we now use Zendesk:
   https://khanacademy.zendesk.com/

Zendesk supports an API for getting all the tickets ever opened, but
we use the incremental API to get all tickets reported since last time.
"""

import base64
import cPickle
import contextlib
import json
import time
import urllib2

import util

# In theory, you can use an API key to access zendesk data, but I
# couldn't get it to work in my tests (I got 'access denied'), so we
# use the real password instead. :-(
ZENDESK_USER = 'prod-read@khanacademy.org'
ZENDESK_PASSWORD_FILE = util.relative_path("zendesk.cfg")
ZENDESK_PASSWORD = None     # set lazily


def _parse_time(s):
    """Convert a string of the form "YYYY-MM-DD HH:MM:SS -0700" to time_t.

    We ignore the -0700; it looks like all times (and time_t's!)
    reported by the API are given as PDT times, so I'm assuming
    they'll change appropriately when daylight savings time ends.
    """
    # We could use strptime, but this is just as easy.
    (yyyy, mm, dd, HH, MM, SS) = (int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                  int(s[11:13]), int(s[14:16]), int(s[17:19]))
    return time.mktime((yyyy, mm, dd, HH, MM, SS, 0, 0, -1))


def get_ticket_data(start_time_t):
    global ZENDESK_PASSWORD
    if ZENDESK_PASSWORD is None:
        with open(ZENDESK_PASSWORD_FILE) as f:
            ZENDESK_PASSWORD = f.read().strip()

    # According to
    #   http://developer.zendesk.com/documentation/rest_api/ticket_export.html
    # "Requests with a start_time less than 5 minutes old will also
    # be rejected."
    if int(time.time()) - start_time_t <= 300:
        return None

    url = ('https://khanacademy.zendesk.com/api/v2/exports/tickets.json'
           '?start_time=%s' % start_time_t)
    request = urllib2.Request(url)
    # This is the best way to set the user, according to
    #    http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
    encoded_password = base64.standard_b64encode('%s:%s' % (ZENDESK_USER,
                                                            ZENDESK_PASSWORD))
    request.add_unredirected_header('Authorization',
                                    'Basic %s' % encoded_password)
    try:
        with contextlib.closing(urllib2.urlopen(request)) as r:
            return json.load(r)
    except urllib2.HTTPError, why:
        if why.code == 429:            # quota limits, wait to try again
            time.sleep(int(why.headers['Retry-After']))
            with contextlib.closing(urllib2.urlopen(request)) as r:
                return json.load(r)
        else:
            raise


def num_tickets_between(start_time_t, end_time_t):
    """Return the number of tickets created between start and end time.

    Also return the time of the oldest ticket seen, as a time_t, which
    is useful for getting an actual date-range when start_time is 0.

    """
    num_tickets = 0
    oldest_ticket_time_t = None

    while start_time_t < end_time_t:
        ticket_data = get_ticket_data(start_time_t)
        if not ticket_data:
            break

        for ticket in ticket_data['results']:
            # I'm guessing the bugs are in the 'Support' group.
            if ticket['group_name'] != 'Support':
                continue

            ticket_time_t = _parse_time(ticket['created_at'])
            if ticket_time_t > end_time_t or ticket_time_t <= start_time_t:
                continue
            num_tickets += 1
            # See if we're the oldest ticket
            if (oldest_ticket_time_t is None or
                    oldest_ticket_time_t > ticket_time_t):
                oldest_ticket_time_t = ticket_time_t

        if not ticket_data['next_page']:
            break
        start_time_t = ticket_data['end_time']

    return (num_tickets, oldest_ticket_time_t)


def main():
    try:
        zendesk_status_file = util.relative_path("zendesk")
        with open(zendesk_status_file) as f:
            old_data = cPickle.load(f)
    except IOError:
        old_data = {"elapsed_time": 0.0001,   # avoid a divide-by-0
                    "ticket_count": 0,
                    "last_time_t": None,
                    }

    # We compare the number of tickets in the last few minutes against
    # the historical average for all time.  But we don't start "all
    # time" at AD 1, we start it a week ago.  Longer than that and it
    # takes forever due to quota issues.  That's still plenty of
    # historical data. :-)
    #
    # Zendesk seems to wait 5 minutes to update API data :-(, so we
    # ask for data that's a bit time-lagged
    now = int(time.time()) - 300
    (num_new_tickets, oldest_ticket_time_t) = num_tickets_between(
        old_data["last_time_t"] or (now - 86400 * 7), now)

    # The first time we run this, we take the starting time to be the
    # time of the first bug report.
    if old_data["last_time_t"] is None:
        old_data["last_time_t"] = oldest_ticket_time_t

    time_this_period = now - old_data["last_time_t"]

    (mean, probability) = util.probability(old_data["ticket_count"],
                                           old_data["elapsed_time"],
                                           num_new_tickets,
                                           time_this_period)

    print ("%s] TOTAL %s/%ss; %s-: %s/%ss; m=%.3f p=%.3f"
           % (time.strftime("%Y-%m-%d %H:%M:%S %Z"),
              old_data["ticket_count"], int(old_data["elapsed_time"]),
              old_data["last_time_t"],
              num_new_tickets, time_this_period,
              mean, probability))

    if (mean != 0 and probability > 0.9995):
        # Too many errors!  Point people to the 'all tickets' filter.
        url = 'https://khanacademy.zendesk.com/agent/filters/37051364'
        util.send_to_slack(
            "*Elevated bug report rate on <%s|Zendesk>*\n"
            "We saw %s in the last %s minutes,"
            " while the mean indicates we should see around %s."
            " *Probability that this is abnormally elevated: %.4f.*"
            % (url,
               util.thousand_commas(num_new_tickets),
               util.thousand_commas(int(time_this_period / 60)),
               util.thousand_commas(round(mean, 2)),
               probability),
            channel='#1s-and-0s')

    new_data = {"elapsed_time": old_data["elapsed_time"] + time_this_period,
                "ticket_count": old_data["ticket_count"] + num_new_tickets,
                "last_time_t": now,
                }
    with open(zendesk_status_file, 'w') as f:
        cPickle.dump(new_data, f)


if __name__ == "__main__":
    main()
